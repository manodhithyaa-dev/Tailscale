#!/usr/bin/env bash
set -Eeuo pipefail

# setup_instance.sh
#
# Creates a Docker container as a lightweight VM-like instance with:
# - automatically allocated instance-N name
# - CPU / RAM limits
# - optional NVIDIA GPU allocation
# - ephemeral container filesystem with /workspace
# - SSH server as PID 1
# - non-root sudo-capable user
# - automatic restart policy
#
# Usage:
#   ./setup_instance.sh <username> <password> <image> <cpu> <ram> <gpu> <storage>

SCRIPT_NAME="$(basename "$0")"
HOST_PORT_START=22001

USERNAME=""
PASSWORD=""
IMAGE=""
CPU=""
RAM=""
GPU=""
STORAGE=""

INSTANCE_NAME=""
HOST_PORT=""
VOLUME_NAME=""
TEMP_CONTAINER=""
CONFIGURED_IMAGE=""
CURRENT_STEP="initialization"

CREATED_CONTAINER=0
CREATED_VOLUME=0
CREATED_IMAGE=0
INTERRUPTED=0
CLEANUP_RUNNING=0
SUCCESS=0


log()  { printf '[INFO] %s\n' "$*"; }
ok()   { printf '[ OK ] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
err()  { printf '[ERROR] %s\n' "$*" >&2; }


step() {
    CURRENT_STEP="$*"
    printf '\n%s\n' "$*"
}


usage() {
    cat <<EOF
Usage:
  $SCRIPT_NAME <username> <password> <image> <cpu> <ram> <gpu> <storage>

Examples:
  $SCRIPT_NAME mano 'mano123' ubuntu:latest 2 2g none 20g
  $SCRIPT_NAME mano 'mano123' alpine:latest 2 2g none 10g
  $SCRIPT_NAME mano 'mano123' ubuntu:latest 4 8g all 50g

Arguments:
  username  Non-root Linux username
  password  Initial password (do not print this value)
  image     Docker image
  cpu       Docker CPU value, e.g. 0.5, 1, 1.5, 2
  ram       Docker memory value, e.g. 512m, 1g, 2g
  gpu       none, all, or a comma-separated GPU device list, e.g. 0 or 0,1
  storage   Accepted for CLI compatibility; ephemeral storage is used

Notes:
  - Storage is ephemeral.
  - Data survives stop/start/restart.
  - Removing the container removes its data.
  - The storage argument does not enforce a hard disk quota.
  - GPU requests require NVIDIA host/container support.
EOF
}


die() {
    err "$*"
    return 1
}


on_interrupt() {
    INTERRUPTED=1

    printf '\n'
    warn "Interrupted by user."

    cleanup

    exit 130
}


cleanup() {
    (( CLEANUP_RUNNING )) && return 0
    CLEANUP_RUNNING=1

    # Remove only resources created by this invocation.

    if [[ -n "$TEMP_CONTAINER" ]]; then
        docker rm -f "$TEMP_CONTAINER" >/dev/null 2>&1 || true
        TEMP_CONTAINER=""
    fi

    if [[ "$SUCCESS" -eq 0 &&
          "$CREATED_CONTAINER" -eq 1 &&
          -n "$INSTANCE_NAME" ]]; then

        log "Removing failed instance: $INSTANCE_NAME"

        docker rm -f "$INSTANCE_NAME" >/dev/null 2>&1 || true
    fi

    if [[ "$SUCCESS" -eq 0 &&
          "$CREATED_IMAGE" -eq 1 &&
          -n "$CONFIGURED_IMAGE" ]]; then

        log "Removing temporary configured image: $CONFIGURED_IMAGE"

        docker image rm "$CONFIGURED_IMAGE" >/dev/null 2>&1 || true
    fi

    CLEANUP_RUNNING=0
}


on_error() {
    local rc=$?

    (( SUCCESS )) && return "$rc"
    (( INTERRUPTED )) && return "$rc"

    printf '\n'

    err "Instance creation failed."
    err "Step      : $CURRENT_STEP"

    [[ -n "$INSTANCE_NAME" ]] &&
        err "Container : $INSTANCE_NAME"

    [[ -n "$IMAGE" ]] &&
        err "Image     : $IMAGE"

    err "Exit code : $rc"

    if [[ -n "$INSTANCE_NAME" ]] &&
       docker container inspect "$INSTANCE_NAME" >/dev/null 2>&1; then

        printf '\n'
        err "Docker logs:"

        docker logs --tail 100 "$INSTANCE_NAME" 2>&1 || true
    fi

    cleanup

    return "$rc"
}


trap on_interrupt INT TERM
trap on_error ERR


require_commands() {
    local missing=()
    local cmd

    for cmd in docker awk grep sed cut tr mktemp; do
        command -v "$cmd" >/dev/null 2>&1 ||
            missing+=("$cmd")
    done

    if ((${#missing[@]})); then
        die "Missing required host command(s): ${missing[*]}"
    fi
}


validate_username() {
    [[ -n "$USERNAME" ]] ||
        die "Username cannot be empty."

    [[ "$USERNAME" != "root" ]] ||
        die "Username 'root' is not allowed."

    [[ "$USERNAME" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] ||
        die "Invalid username '$USERNAME'. Use 1-32 chars: lowercase letters, digits, '_' or '-'."
}


validate_password() {
    [[ -n "$PASSWORD" ]] ||
        die "Password cannot be empty."
}


validate_cpu() {
    [[ "$CPU" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]] ||
        die "Invalid CPU value '$CPU'. Use a positive decimal such as 0.5, 1, 1.5, or 2."

    awk -v n="$CPU" 'BEGIN { exit !(n > 0) }' ||
        die "CPU must be greater than zero."
}


validate_memory() {
    [[ "$RAM" =~ ^[1-9][0-9]*([kKmMgGtT][iI]?[bB]?)?$ ]] ||
        die "Invalid RAM value '$RAM'. Examples: 512m, 1g, 2g, 8g."

    [[ "$RAM" =~ [bBkKmMgGtT]$ ||
       "$RAM" =~ [bBkKmMgGtT][bBiI]$ ]] ||
        warn "RAM '$RAM' has no explicit unit; Docker may interpret it as bytes."
}


validate_storage() {
    [[ "$STORAGE" =~ ^[1-9][0-9]*([kKmMgGtT][iI]?[bB]?)$ ]] ||
        die "Invalid storage value '$STORAGE'. Examples: 10g, 20g, 1t."
}


validate_gpu() {
    case "$GPU" in
        none|all)
            ;;

        '')
            die "GPU cannot be empty. Use none, all, or a device list such as 0 or 0,1."
            ;;

        *)
            [[ "$GPU" =~ ^[0-9]+(,[0-9]+)*$ ]] ||
                die "Invalid GPU '$GPU'. Use none, all, or a comma-separated device list such as 0,1."
            ;;
    esac
}


validate_arguments() {
    if [[ "$#" -ne 7 ]]; then
        usage >&2
        die "Expected exactly 7 arguments; received $#."
    fi

    USERNAME="$1"
    PASSWORD="$2"
    IMAGE="$3"
    CPU="$4"
    RAM="$5"
    GPU="$6"
    STORAGE="$7"

    validate_username
    validate_password

    [[ -n "$IMAGE" ]] ||
        die "Image cannot be empty."

    validate_cpu
    validate_memory
    validate_gpu
    validate_storage
}


check_docker() {
    docker info >/dev/null
    ok "Docker is available."
}


image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}


ensure_image() {
    if image_exists "$IMAGE"; then
        ok "$IMAGE available locally."
        return
    fi

    log "Image '$IMAGE' is not present locally; pulling it now..."

    if ! docker pull "$IMAGE"; then
        die "Failed to pull image '$IMAGE'."
    fi

    ok "$IMAGE pulled successfully."
}


find_instance_name() {
    local n=1

    while docker container inspect "instance-$n" >/dev/null 2>&1; do
        n=$((n + 1))
    done

    INSTANCE_NAME="instance-$n"

    # No Docker volume is used.
    VOLUME_NAME=""

    ok "Instance: $INSTANCE_NAME"
}


host_port_is_free() {
    local port="$1"

    if ss -ltnH 2>/dev/null |
       awk '{print $4}' |
       grep -Eq "(^|:)${port}$"; then
        return 1
    fi

    if command -v lsof >/dev/null 2>&1 &&
       lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        return 1
    fi

    # Check Docker's published ports.
    if docker ps --format '{{.Ports}}' |
       grep -Eq "(^|[^0-9])${port}->"; then
        return 1
    fi

    return 0
}


find_free_port() {
    local port="$HOST_PORT_START"

    while (( port <= 65535 )); do

        if host_port_is_free "$port"; then
            HOST_PORT="$port"

            ok "SSH port candidate: $HOST_PORT"

            return
        fi

        port=$((port + 1))
    done

    die "No free host TCP port found from $HOST_PORT_START onward."
}


gpu_args() {
    case "$GPU" in
        none)
            printf '%s\n' ""
            ;;

        all)
            printf '%s\n' "--gpus=all"
            ;;

        *)
            printf '%s\n' "--gpus=device=$GPU"
            ;;
    esac
}


check_gpu_support() {
    [[ "$GPU" == "none" ]] && return 0

    log "Checking NVIDIA GPU support..."

    command -v nvidia-smi >/dev/null 2>&1 ||
        die "GPU '$GPU' requested, but nvidia-smi is not installed on the host."

    nvidia-smi -L >/dev/null 2>&1 ||
        die "GPU '$GPU' requested, but NVIDIA GPUs are not accessible on the host."

    docker info 2>/dev/null |
        grep -qE 'Runtimes:.*nvidia|nvidia' ||
        die "GPU '$GPU' requested, but Docker does not report NVIDIA runtime support. Install/configure NVIDIA Container Toolkit first."

    if [[ "$GPU" != "all" ]]; then

        local max_index

        max_index="$(
            nvidia-smi \
                --query-gpu=index \
                --format=csv,noheader 2>/dev/null |
            sort -n |
            tail -1
        )"

        [[ -n "$max_index" ]] ||
            die "Could not determine available NVIDIA GPU indices."

        local item

        IFS=',' read -r -a gpu_list <<< "$GPU"

        for item in "${gpu_list[@]}"; do

            awk \
                -v requested="$item" \
                -v maximum="$max_index" \
                'BEGIN {
                    exit !(requested >= 0 && requested <= maximum)
                }' ||
                die "Requested GPU index '$item' is not available."

        done
    fi

    ok "NVIDIA GPU support is available for request '$GPU'."
}


create_volume() {
    # Intentionally no Docker volume is created.
    #
    # The container's writable filesystem is used.
    # /workspace is created inside the configured image.
    #
    # Removing the container removes its data.

    VOLUME_NAME=""

    ok "Ephemeral storage enabled."

    warn "Storage argument '$STORAGE' is accepted for CLI compatibility only."

    warn "No persistent Docker volume is created; data is lost when the container is removed."
}


docker_run_with_retry() {
    local requested_port="$HOST_PORT"
    local attempt=0
    local max_attempts=50
    local rc

    local -a run_args=("$@")

    while ((attempt < max_attempts)); do

        if host_port_is_free "$HOST_PORT"; then

            log "Creating container with SSH mapping localhost:${HOST_PORT}:22"

        else

            HOST_PORT=$((HOST_PORT + 1))
            attempt=$((attempt + 1))

            continue
        fi

        set +e

        docker run \
            "${run_args[@]}" \
            -p "${HOST_PORT}:22" \
            --name "$INSTANCE_NAME" \
            --hostname "$INSTANCE_NAME" \
            --restart unless-stopped \
            "$CONFIGURED_IMAGE"

        rc=$?

        set -e

        if ((rc == 0)); then

            CREATED_CONTAINER=1

            return 0
        fi

        if docker container inspect "$INSTANCE_NAME" >/dev/null 2>&1; then
            docker rm -f "$INSTANCE_NAME" >/dev/null 2>&1 || true
        fi

        if ((rc != 0)) &&
           ((attempt + 1 < max_attempts)); then

            warn "docker run failed on host port $HOST_PORT (exit $rc). Retrying with the next port..."

            HOST_PORT=$((HOST_PORT + 1))
            attempt=$((attempt + 1))

            continue
        fi

        return "$rc"
    done

    die "Unable to create instance after $max_attempts port attempts (starting at $requested_port)."
}


create_temp_container() {
    TEMP_CONTAINER="instance-build-$$-$RANDOM"

    log "Creating temporary configuration container: $TEMP_CONTAINER"

    local -a args=(
        --name "$TEMP_CONTAINER"
        --hostname "$TEMP_CONTAINER"
        --entrypoint /bin/sh
    )

    if [[ "$GPU" != "none" ]]; then
        args+=( "$(gpu_args)" )
    fi

    docker run \
        -d \
        "${args[@]}" \
        "$IMAGE" \
        -c 'while :; do sleep 3600; done' >/dev/null

    ok "Temporary container created."
}


exec_in_temp() {
    docker exec "$TEMP_CONTAINER" "$@"
}


detect_package_manager() {
    local manager

    for manager in apk apt-get dnf yum; do

        if exec_in_temp \
            /bin/sh \
            -c "command -v $manager >/dev/null 2>&1"; then

            printf '%s\n' "$manager"

            return 0
        fi
    done

    die "Unsupported container OS: no apk, apt-get, dnf, or yum package manager found."
}


install_ssh() {
    local pm="$1"

    case "$pm" in

        apk)

            log "Installing OpenSSH, sudo, bash and required tools with apk..."

            exec_in_temp \
                /bin/sh \
                -c \
                'apk update && apk add --no-cache openssh sudo bash shadow'

            ;;

        apt-get)

            log "Installing OpenSSH, sudo and bash with apt-get..."

            exec_in_temp \
                /bin/sh \
                -c \
                'export DEBIAN_FRONTEND=noninteractive
                 apt-get update
                 apt-get install -y --no-install-recommends openssh-server sudo bash
                 rm -rf /var/lib/apt/lists/*'

            ;;

        dnf)

            log "Installing OpenSSH, sudo and bash with dnf..."

            exec_in_temp \
                /bin/sh \
                -c \
                'dnf install -y openssh-server sudo bash shadow-utils
                 dnf clean all'

            ;;

        yum)

            log "Installing OpenSSH, sudo and bash with yum..."

            exec_in_temp \
                /bin/sh \
                -c \
                'yum install -y openssh-server sudo bash shadow-utils
                 yum clean all'

            ;;

        *)

            die "Internal error: unsupported package manager '$pm'."

            ;;
    esac

    ok "SSH packages installed."
}


create_user() {
    local pm="$1"

    : "$pm"

    log "Creating non-root user '$USERNAME'..."

    docker exec \
        -e SETUP_USERNAME="$USERNAME" \
        -e SETUP_PASSWORD="$PASSWORD" \
        "$TEMP_CONTAINER" \
        /bin/sh \
        -c \
        '
        set -eu

        if id "$SETUP_USERNAME" >/dev/null 2>&1; then
            echo "User already exists in the base image: $SETUP_USERNAME" >&2
            exit 20
        fi

        # Determine the login shell.
        shell=/bin/bash
        [ -x "$shell" ] || shell=/bin/sh

        # Create the user.
        if command -v useradd >/dev/null 2>&1; then

            useradd \
                -m \
                -s "$shell" \
                "$SETUP_USERNAME"

        elif command -v adduser >/dev/null 2>&1; then

            # Alpine-style adduser.
            adduser \
                -D \
                -s "$shell" \
                "$SETUP_USERNAME"

        else

            echo "Neither useradd nor adduser is available." >&2
            exit 21
        fi

        # Set password.
        #
        # Prefer chpasswd because it works reliably with Amazon Linux,
        # Debian/Ubuntu and Alpine when the appropriate shadow tools exist.
        #
        # Password is passed through an environment variable and stdin.
        # It is never interpolated into a shell command.
        if command -v chpasswd >/dev/null 2>&1; then

            printf "%s:%s\n" \
                "$SETUP_USERNAME" \
                "$SETUP_PASSWORD" |
                chpasswd

        elif command -v passwd >/dev/null 2>&1; then

            printf "%s\n%s\n" \
                "$SETUP_PASSWORD" \
                "$SETUP_PASSWORD" |
                passwd "$SETUP_USERNAME"

        else

            echo "Neither chpasswd nor passwd is available." >&2
            exit 22
        fi

        unset SETUP_PASSWORD
        '

    docker exec \
        -e SETUP_USERNAME="$USERNAME" \
        "$TEMP_CONTAINER" \
        /bin/sh \
        -c \
        '
        set -eu

        # Configure sudo/wheel privileges.
        if getent group sudo >/dev/null 2>&1; then

            if command -v usermod >/dev/null 2>&1; then

                usermod \
                    -aG sudo \
                    "$SETUP_USERNAME"

            elif command -v addgroup >/dev/null 2>&1; then

                addgroup \
                    "$SETUP_USERNAME" \
                    sudo

            else

                echo "Cannot add user to sudo group." >&2
                exit 23
            fi

            printf "%s ALL=(ALL) NOPASSWD: ALL\n" \
                "$SETUP_USERNAME" \
                > /etc/sudoers.d/90-instance-user

        elif getent group wheel >/dev/null 2>&1; then

            if command -v usermod >/dev/null 2>&1; then

                usermod \
                    -aG wheel \
                    "$SETUP_USERNAME"

            elif command -v addgroup >/dev/null 2>&1; then

                addgroup \
                    "$SETUP_USERNAME" \
                    wheel

            else

                echo "Cannot add user to wheel group." >&2
                exit 24
            fi

            printf "%%wheel ALL=(ALL) NOPASSWD: ALL\n" \
                > /etc/sudoers.d/90-instance-user

        else

            echo "No sudo or wheel group available." >&2
            exit 25
        fi

        chmod 0440 /etc/sudoers.d/90-instance-user
        '

    ok "User '$USERNAME' created with sudo/admin privileges."
}


configure_ssh() {
    log "Configuring sshd..."

    docker exec \
        "$TEMP_CONTAINER" \
        /bin/sh \
        -c \
        '
        set -eu

        mkdir -p /run/sshd
        chmod 0755 /run/sshd

        if [ -f /etc/ssh/sshd_config ]; then

            sed -i \
                -e "/^[[:space:]]*#\{0,1\}PasswordAuthentication[[:space:]]/d" \
                -e "/^[[:space:]]*#\{0,1\}PermitRootLogin[[:space:]]/d" \
                -e "/^[[:space:]]*#\{0,1\}PubkeyAuthentication[[:space:]]/d" \
                -e "/^[[:space:]]*#\{0,1\}KbdInteractiveAuthentication[[:space:]]/d" \
                /etc/ssh/sshd_config

        else

            touch /etc/ssh/sshd_config
        fi

        cat >> /etc/ssh/sshd_config <<EOF
PasswordAuthentication yes
PermitRootLogin no
PubkeyAuthentication yes
KbdInteractiveAuthentication yes
EOF

        ssh-keygen -A

        sshd_bin=""

        for candidate in \
            /usr/sbin/sshd \
            /usr/sbin/dropbear; do

            if [ -x "$candidate" ]; then

                sshd_bin="$candidate"

                break
            fi
        done

        [ -n "$sshd_bin" ] || {
            echo "No supported SSH daemon found." >&2
            exit 30
        }

        case "$sshd_bin" in

            */sshd)

                "$sshd_bin" -t

                ;;

            *)

                echo "Unsupported SSH daemon for validation: $sshd_bin" >&2

                exit 31

                ;;
        esac

        chmod 0755 /run/sshd
        '

    ok "sshd configuration validated."
}


configure_entrypoint() {
    log "Configuring lightweight SSH entrypoint..."

    docker exec \
        "$TEMP_CONTAINER" \
        /bin/sh \
        -c \
        '
        set -eu

        cat > /usr/local/bin/instance-entrypoint <<'"'"'EOF'"'"'
#!/bin/sh
set -eu

mkdir -p /run/sshd
chmod 0755 /run/sshd

exec /usr/sbin/sshd -D -e
EOF

        chmod 0755 /usr/local/bin/instance-entrypoint

        # Ephemeral workspace.
        mkdir -p /workspace
        chmod 0755 /workspace

        if [ ! -x /usr/sbin/sshd ]; then

            echo "/usr/sbin/sshd not found." >&2

            exit 40
        fi

        /usr/sbin/sshd -t
        '

    ok "SSH entrypoint configured."
}


commit_configured_image() {
    CONFIGURED_IMAGE="instance-configured:${INSTANCE_NAME}-$$"

    log "Creating configured image: $CONFIGURED_IMAGE"

    docker commit \
        --change 'ENTRYPOINT ["/usr/local/bin/instance-entrypoint"]' \
        --change 'CMD []' \
        "$TEMP_CONTAINER" \
        "$CONFIGURED_IMAGE" >/dev/null

    CREATED_IMAGE=1

    ok "Configured image created."
}


remove_temp_container() {
    docker rm -f "$TEMP_CONTAINER" >/dev/null 2>&1 || true

    TEMP_CONTAINER=""

    ok "Temporary container removed."
}


create_final_container() {
    local -a run_args=(
        -d
        --cpus="$CPU"
        --memory="$RAM"
    )

    if [[ "$GPU" != "none" ]]; then
        run_args+=( "$(gpu_args)" )
    fi

    step "[4/9] Allocating instance..."

    docker_run_with_retry "${run_args[@]}"

    ok "Final instance created."
    ok "SSH port: $HOST_PORT"
}


install_and_configure() {
    local pm

    step "[5/9] Preparing container..."

    create_temp_container

    pm="$(detect_package_manager)"

    ok "Package manager detected: $pm"

    install_ssh "$pm"
    create_user "$pm"
    configure_ssh
    configure_entrypoint
    commit_configured_image
    remove_temp_container

    step "[6/9] Applying resources..."

    ok "CPU: $CPU"
    ok "RAM: $RAM"
    ok "GPU: $GPU"
    ok "Storage: $STORAGE requested (ephemeral)"
}


start_instance() {
    step "[7/9] Starting instance..."

    # docker run -d already starts the container.
    # This explicit start verifies Docker accepts the container lifecycle.

    docker start "$INSTANCE_NAME" >/dev/null 2>&1 || true

    sleep 1

    docker inspect \
        -f '{{.State.Running}}' \
        "$INSTANCE_NAME" |
        grep -qx true ||
        die "Instance did not remain running."

    ok "SSH container is running."
}


verify_docker() {
    local running
    local restart_policy
    local cpus
    local memory
    local port

    running="$(
        docker inspect \
            -f '{{.State.Running}}' \
            "$INSTANCE_NAME"
    )"

    [[ "$running" == "true" ]] ||
        die "Container is not running."

    restart_policy="$(
        docker inspect \
            -f '{{.HostConfig.RestartPolicy.Name}}' \
            "$INSTANCE_NAME"
    )"

    [[ "$restart_policy" == "unless-stopped" ]] ||
        die "Restart policy is '$restart_policy', expected 'unless-stopped'."

    cpus="$(
        docker inspect \
            -f '{{.HostConfig.NanoCpus}}' \
            "$INSTANCE_NAME"
    )"

    memory="$(
        docker inspect \
            -f '{{.HostConfig.Memory}}' \
            "$INSTANCE_NAME"
    )"

    [[ "$cpus" != "0" ]] ||
        die "CPU limit was not applied."

    [[ "$memory" != "0" ]] ||
        die "Memory limit was not applied."

    port="$(
        docker port \
            "$INSTANCE_NAME" \
            22/tcp 2>/dev/null |
        head -n1
    )"

    [[ "$port" == *":${HOST_PORT}"* ]] ||
        die "SSH port mapping is missing or incorrect: '$port'."

    ok "Docker configuration verified."
}


verify_inside_container() {

    docker exec \
        "$INSTANCE_NAME" \
        /bin/sh \
        -c \
        '
        set -eu

        test -d /run/sshd
        test -x /usr/sbin/sshd

        /usr/sbin/sshd -t
        '

    docker exec \
        "$INSTANCE_NAME" \
        /bin/sh \
        -c \
        'id "$1"' \
        sh \
        "$USERNAME" >/dev/null

    docker exec \
        "$INSTANCE_NAME" \
        /bin/sh \
        -c \
        'sudo -n -u "$1" id >/dev/null' \
        sh \
        "$USERNAME"

    docker exec \
        "$INSTANCE_NAME" \
        /bin/sh \
        -c \
        'test -d /workspace'

    local pid_cmd

    pid_cmd="$(
        docker exec \
            "$INSTANCE_NAME" \
            /bin/sh \
            -c \
            'tr "\0" " " </proc/1/cmdline' \
            2>/dev/null ||
        true
    )"

    [[ "$pid_cmd" == *"sshd -D -e"* ]] ||
        die "PID 1 is not sshd -D -e. Actual: $pid_cmd"

    ok "SSH, user, sudo and /workspace checks passed."
}


test_restart() {
    step "[8/9] Testing restart..."

    docker restart "$INSTANCE_NAME" >/dev/null

    sleep 1

    docker inspect \
        -f '{{.State.Running}}' \
        "$INSTANCE_NAME" |
        grep -qx true ||
        die "Container is not running after restart."

    docker exec \
        "$INSTANCE_NAME" \
        /bin/sh \
        -c \
        'test -d /workspace && /usr/sbin/sshd -t'

    docker exec \
        "$INSTANCE_NAME" \
        /bin/sh \
        -c \
        'id "$1"' \
        sh \
        "$USERNAME" >/dev/null

    local pid_cmd

    pid_cmd="$(
        docker exec \
            "$INSTANCE_NAME" \
            /bin/sh \
            -c \
            'tr "\0" " " </proc/1/cmdline' \
            2>/dev/null ||
        true
    )"

    [[ "$pid_cmd" == *"sshd -D -e"* ]] ||
        die "sshd is not PID 1 after restart."

    ok "Restart test passed."
}


test_ssh() {
    if ! command -v sshpass >/dev/null 2>&1; then

        warn "sshpass not installed; skipping automated password SSH test."

        return 0
    fi

    log "Running real SSH login test..."

    local output

    set +e

    output="$(
        SSHPASS="$PASSWORD" \
        sshpass -e ssh \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o PubkeyAuthentication=no \
            -o PreferredAuthentications=password \
            -o ConnectTimeout=5 \
            -p "$HOST_PORT" \
            "$USERNAME@127.0.0.1" \
            'id -u && test -d /workspace' \
        2>&1
    )"

    local rc=$?

    set -e

    if ((rc != 0)); then

        err "Automated SSH test failed:"

        printf '%s\n' "$output" >&2

        return "$rc"
    fi

    ok "Real SSH login test passed."
}


print_success() {
    step "[9/9] Verifying..."

    verify_docker
    verify_inside_container
    test_restart
    test_ssh

    ok "Instance verified."

    printf '\n'

    printf '%s\n' \
        '============================================================'

    printf '%s\n' \
        '                     INSTANCE READY'

    printf '%s\n' \
        '============================================================'

    printf 'Instance : %s\n' "$INSTANCE_NAME"
    printf 'Image    : %s\n' "$IMAGE"
    printf 'CPU      : %s\n' "$CPU"
    printf 'RAM      : %s\n' "$RAM"
    printf 'GPU      : %s\n' "$GPU"
    printf 'Storage  : %s requested (ephemeral)\n' "$STORAGE"
    printf 'Volume   : none\n'
    printf 'User     : %s\n' "$USERNAME"
    printf 'SSH      : localhost:%s\n' "$HOST_PORT"

    printf '\n'

    printf '%s\n' 'Connect:'

    printf \
        '    ssh -p %s %s@localhost\n' \
        "$HOST_PORT" \
        "$USERNAME"

    printf '\n'

    printf '%s\n' 'Docker:'

    printf \
        '    docker exec -it %s bash\n' \
        "$INSTANCE_NAME"

    printf '\n'

    printf '%s\n' 'Workspace (ephemeral):'

    printf \
        '    /workspace\n'

    printf '\n'

    printf '%s\n' 'Manage:'

    printf \
        '    docker stop %s\n' \
        "$INSTANCE_NAME"

    printf \
        '    docker start %s\n' \
        "$INSTANCE_NAME"

    printf \
        '    docker restart %s\n' \
        "$INSTANCE_NAME"

    printf \
        '    docker rm -f %s\n' \
        "$INSTANCE_NAME"

    printf '\n'

    printf '%s\n' \
        'Storage: ephemeral; removing the container removes its data.'

    printf '%s\n' \
        '============================================================'
}


main() {

    printf '%s\n' \
        '============================================================'

    printf '%s\n' \
        '             DOCKER INSTANCE CREATOR'

    printf '%s\n' \
        '============================================================'


    step "[1/9] Validating arguments..."

    validate_arguments "$@"

    ok "Arguments valid."


    step "[2/9] Checking Docker..."

    require_commands
    check_docker


    step "[3/9] Checking image and host capabilities..."

    ensure_image
    check_gpu_support
    find_instance_name
    find_free_port

    ok "Image and host checks passed."

    create_volume

    install_and_configure

    create_final_container

    start_instance

    print_success

    SUCCESS=1

    cleanup
}


main "$@"
