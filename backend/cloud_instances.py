"""
Commands
Operation	Command
Create Ubuntu	python3 cloud_instances.py create --name vm1 --os ubuntu --cpu 2 --ram 2048 --storage 20
Create Debian	python3 cloud_instances.py create --name vm2 --os debian --cpu 1 --ram 1024 --storage 10
Stop	python3 cloud_instances.py stop vm1
Restart	python3 cloud_instances.py restart vm1
Terminate, preserve data	python3 cloud_instances.py terminate vm1
Terminate and delete data	python3 cloud_instances.py terminate vm1 --delete-data
List all instances	python3 cloud_instances.py list
"""

import argparse
import docker
import getpass
import re
import secrets
import string

client = docker.from_env()

IMAGES = {
    "ubuntu": "ubuntu:latest",
    "debian": "debian:latest",
    "alpine": "alpine:latest",
    "amazonlinux": "amazonlinux:latest",
}


def valid_name(name):
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", name))


def get_instance(name):
    try:
        return client.containers.get(name)
    except docker.errors.NotFound:
        print(f"Instance '{name}' not found.")
        return None


def create_instance(args):
    if not valid_name(args.name):
        print("Invalid instance name.")
        return

    if args.os not in IMAGES:
        print(f"Supported OS: {', '.join(IMAGES)}")
        return

    if not (1 <= args.cpu <= 4):
        print("CPU must be between 1 and 4 cores.")
        return

    if not (256 <= args.ram <= 8192):
        print("RAM must be between 256 and 8192 MB.")
        return

    if not (1 <= args.storage <= 100):
        print("Storage must be between 1 and 100 GB.")
        return

    try:
        client.containers.get(args.name)
        print("An instance with this name already exists.")
        return
    except docker.errors.NotFound:
        pass

    image = IMAGES[args.os]
    try:
        client.images.get(image)
        print(f"Using local image: {image}")
    except docker.errors.ImageNotFound:
        print(f"Image not found locally. Downloading: {image}")
        client.images.pull(image)

    volume = client.volumes.create(name=f"{args.name}-data")

    try:
        container = client.containers.run(
            image=image,
            name=args.name,
            command=[
                "sh", "-c",
                "while true; do sleep 3600; done"
            ],
            detach=True,
            tty=True,
            stdin_open=True,
            nano_cpus=int(args.cpu * 1_000_000_000),
            mem_limit=f"{args.ram}m",
            volumes={
                volume.name: {
                    "bind": "/data",
                    "mode": "rw"
                }
            },
            labels={
                "cloud.instance": "true",
                "cloud.os": args.os,
                "cloud.storage_gb": str(args.storage),
            },
            restart_policy={"Name": "unless-stopped"},
        )

        print("\nInstance created successfully!")
        print(f"Name:    {container.name}")
        print(f"ID:      {container.short_id}")
        print(f"OS:      {args.os}")
        print(f"CPU:     {args.cpu} cores")
        print(f"RAM:     {args.ram} MB")
        print(f"Storage: {args.storage} GB requested (not enforced)")
        print(f"Status:  {container.status}")
        print(f"Volume:  {volume.name} -> /data")

    except Exception as exc:
        print(f"Creation failed: {exc}")
        try:
            volume.remove(force=True)
        except docker.errors.APIError:
            pass


def stop_instance(name):
    container = get_instance(name)
    if container:
        container.stop(timeout=10)
        print(f"Instance '{name}' stopped.")


def restart_instance(name):
    container = get_instance(name)
    if container:
        container.restart(timeout=10)
        print(f"Instance '{name}' restarted.")


def terminate_instance(name, delete_data=False):
    container = get_instance(name)
    if not container:
        return

    volume_name = f"{name}-data"
    container.remove(force=True)
    print(f"Instance '{name}' terminated.")

    # Preserve data by default; delete it only when explicitly requested.
    if delete_data:
        try:
            client.volumes.get(volume_name).remove(force=True)
            print(f"Volume '{volume_name}' deleted.")
        except docker.errors.NotFound:
            pass
    else:
        print(f"Persistent data retained in volume '{volume_name}'.")


def list_instances():
    instances = client.containers.list(
        all=True,
        filters={"label": "cloud.instance=true"}
    )

    if not instances:
        print("No cloud instances found.")
        return

    print(f"{'NAME':<22} {'STATUS':<12} {'IMAGE':<22} ID")
    print("-" * 75)

    for container in instances:
        print(
            f"{container.name:<22} "
            f"{container.status:<12} "
            f"{container.image.tags[0] if container.image.tags else 'unknown':<22} "
            f"{container.short_id}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Docker Cloud Instance Manager"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    create = sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--os", choices=IMAGES, default="ubuntu")
    create.add_argument("--cpu", type=float, default=1)
    create.add_argument("--ram", type=int, default=1024)
    create.add_argument("--storage", type=int, default=10)

    for action in ("stop", "restart"):
        command = sub.add_parser(action)
        command.add_argument("name")

    terminate = sub.add_parser("terminate")
    terminate.add_argument("name")
    terminate.add_argument(
        "--delete-data",
        action="store_true",
        help="Also delete the persistent data volume"
    )

    sub.add_parser("list")

    args = parser.parse_args()

    try:
        if args.action == "create":
            create_instance(args)
        elif args.action == "stop":
            stop_instance(args.name)
        elif args.action == "restart":
            restart_instance(args.name)
        elif args.action == "terminate":
            terminate_instance(args.name, args.delete_data)
        elif args.action == "list":
            list_instances()

    except docker.errors.DockerException as exc:
        print(f"Docker error: {exc}")


if __name__ == "__main__":
    main()
