#!/usr/bin/env bash
# ============================================================
# MySQL FastAPI test script
# Usage:  ./test_api.sh [SERVER_IP] [PORT]
# Example:./test_api.sh 127.0.0.1     # server PC
#        ./test_api.sh 100.x.x.x     # client PC (Tailscale IP)
# ============================================================

set -u

SERVER_IP="${1:-127.0.0.1}"
PORT="${2:-1234}"
BASE="http://${SERVER_IP}:${PORT}"

# ---- EDIT THESE ----
DB_HOST="127.0.0.1"
DB_PORT="3306"
DB_USER="root"
DB_PASS=""            # <-- set your password
DB_NAME="test_trial"
# --------------------

CURL="curl -sS --max-time 15"
GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

run() {
  local title="$1" desc="$2" payload="$3"
  echo
  echo "${YELLOW}== ${title}${NC}  (${desc})"
  $CURL -X POST "$BASE$4" -H "Content-Type: application/json" -d "$payload" \
    | { python3 -m json.tool 2>/dev/null || cat; }
}

health() {
  echo "${YELLOW}== Health check: GET /${NC}"
  $CURL "$BASE/"
  echo
}

test_ok() {
  run "$1" "$2" '{"host":"'"$DB_HOST"'","port":'"$DB_PORT"',"user":"'"$DB_USER"'","password":"'"$DB_PASS"'","database":"'"$DB_NAME"'"}' "$3"
}

test_query() {
  run "$1" "$2" '{"host":"'"$DB_HOST"'","port":'"$DB_PORT"',"user":"'"$DB_USER"'","password":"'"$DB_PASS"'","database":"'"$DB_NAME"'","query":"'"$3"'","max_rows":100}' "/query"
}

health

test_ok  "1. Test MySQL connection"   "POST /test-db"   "/test-db"
test_ok  "2. List tables"             "POST /tables"    "/tables"
test_ok  "3. Database info"           "POST /database-info" "/database-info"
run      "4. Inspect table 'users'"   "POST /table-info" \
  '{"host":"'"$DB_HOST"'","port":'"$DB_PORT"',"user":"'"$DB_USER"'","password":"'"$DB_PASS"'","database":"'"$DB_NAME"'","table":"users"}' \
  "/table-info"

test_query "5. SELECT"                 "SELECT * FROM users LIMIT 20"
test_query "6. INSERT (safe demo)"     "INSERT INTO users (name) VALUES ('curl-test')"
test_query "7. Multiple statements"    "SELECT COUNT(*) AS n FROM users; SELECT NOW()"

echo
echo "${GREEN}---- ERROR-PATH TESTS (expect 400, never leak password) ----${NC}"

test_query "8.  Syntax error"  "select * users limit 1"
test_query "9.  Unknown table" "SELECT * FROM nonexistent_table"
run "10. Wrong password" "POST /test-db" \
  '{"host":"'"$DB_HOST"'","port":'"$DB_PORT"',"user":"'"$DB_USER"'","password":"WRONG","database":"'"$DB_NAME"'"}' \
  "/test-db"
run "11. Unknown database" "POST /test-db" \
  '{"host":"'"$DB_HOST"'","port":'"$DB_PORT"',"user":"'"$DB_USER"'","password":"'"$DB_PASS"'","database":"db_does_not_exist"}' \
  "/test-db"
test_query "12. Empty query" "        "

echo
echo "Server listen check:  sudo ss -lntp | grep $PORT"