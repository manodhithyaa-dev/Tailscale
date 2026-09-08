import requests
import getpass
import sys


# ============================================================
# TIMEOUT
# ============================================================

TIMEOUT = 15


# ============================================================
# DISPLAY HELPERS
# ============================================================

def print_header(title):
    print()
    print("=" * 60)
    print(title.center(60))
    print("=" * 60)


def print_error(message):
    print()
    print("## ERROR")
    print()
    print(message)
    print()


def print_success(message):
    print()
    print(f"OK: {message}")
    print()


# ============================================================
# COLLECT SERVER CONFIG
# ============================================================

def get_server_config():
    print_header("MYSQL REMOTE CLIENT")

    server_ip = input("\nServer Tailscale IP [100.x.x.x]: ").strip()
    if not server_ip:
        print_error("Server IP is required.")
        sys.exit(1)

    server_port = input("Server API Port [1234]: ").strip()
    if not server_port:
        server_port = "1234"

    base_url = f"http://{server_ip}:{server_port}"

    return base_url


# ============================================================
# COLLECT MYSQL CONFIG
# ============================================================

def get_mysql_config():
    print_header("MYSQL DATABASE CONFIGURATION")

    db_host = input("\nMySQL Host [127.0.0.1]: ").strip()
    if not db_host:
        db_host = "127.0.0.1"

    db_port = input("MySQL Port [3306]: ").strip()
    if not db_port:
        db_port = "3306"

    db_user = input("MySQL Username: ").strip()
    if not db_user:
        print_error("Username is required.")
        sys.exit(1)

    db_password = getpass.getpass("MySQL Password: ")

    db_name = input("MySQL Database Name: ").strip()
    if not db_name:
        print_error("Database name is required.")
        sys.exit(1)

    return {
        "host": db_host,
        "port": int(db_port),
        "user": db_user,
        "password": db_password,
        "database": db_name
    }


# ============================================================
# API CALL HELPERS
# ============================================================

def api_get(base_url, path):
    try:
        response = requests.get(
            f"{base_url}{path}",
            timeout=TIMEOUT
        )
        return response
    except requests.exceptions.ConnectionError:
        print_error(
            "Cannot connect to FastAPI server.\n\n"
            "Check:\n"
            "  1. Tailscale is running\n"
            "  2. Server IP is correct\n"
            "  3. Uvicorn is running on the server\n"
            "  4. API port is correct\n"
            "  5. Firewall allows port on Tailscale interface"
        )
        return None
    except requests.exceptions.Timeout:
        print_error("Request timed out.")
        return None
    except Exception as e:
        print_error(f"Request failed: {e}")
        return None


def api_post(base_url, path, data):
    try:
        response = requests.post(
            f"{base_url}{path}",
            json=data,
            timeout=TIMEOUT
        )
        return response
    except requests.exceptions.ConnectionError:
        print_error(
            "Cannot connect to FastAPI server.\n\n"
            "Check:\n"
            "  1. Tailscale is running\n"
            "  2. Server IP is correct\n"
            "  3. Uvicorn is running on the server\n"
            "  4. API port is correct\n"
            "  5. Firewall allows port on Tailscale interface"
        )
        return None
    except requests.exceptions.Timeout:
        print_error("Request timed out.")
        return None
    except Exception as e:
        print_error(f"Request failed: {e}")
        return None


def handle_api_error(response, action_name):
    if response is None:
        return True

    if response.status_code == 404:
        print_error(f"{action_name} failed: Endpoint not found (404).")
        return True

    if response.status_code == 422:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print_error(f"{action_name} failed: Invalid request (422).\n\n{detail}")
        return True

    if response.status_code == 500:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print_error(f"{action_name} failed: Server error (500).\n\n{detail}")
        return True

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print_error(f"{action_name} failed (HTTP {response.status_code}).\n\n{detail}")
        return True

    return False


# ============================================================
# STEP 1: CHECK SERVER
# ============================================================

def check_server(base_url):
    print_header("CHECKING SERVER")
    print(f"\nServer: {base_url}")

    response = api_get(base_url, "/")

    if handle_api_error(response, "Server check"):
        return False

    data = response.json()
    print_success(f"Server reachable. Status: {data.get('status', 'unknown')}")
    return True


# ============================================================
# STEP 2: TEST MYSQL
# ============================================================

def test_mysql(base_url, db_config):
    print_header("TESTING MYSQL CONNECTION")

    response = api_post(base_url, "/test-db", db_config)

    if handle_api_error(response, "MySQL test"):
        return False

    data = response.json()

    if data.get("success"):
        print_success(
            f"MySQL connection successful\n"
            f"  Database: {data.get('database', 'unknown')}\n"
            f"  MySQL Version: {data.get('mysql_version', 'unknown')}"
        )
        return True
    else:
        print_error(f"MySQL connection failed.\n\n{data.get('message', 'Unknown error')}")
        return False


# ============================================================
# STEP 3: LIST TABLES
# ============================================================

def list_tables(base_url, db_config):
    print_header("LISTING TABLES")

    response = api_post(base_url, "/tables", db_config)

    if handle_api_error(response, "List tables"):
        return []

    data = response.json()

    if data.get("success"):
        tables = data.get("tables", [])

        print(f"\nDatabase: {data.get('database', 'unknown')}\n")

        if not tables:
            print("No tables exist in this database.\n")
        else:
            print("Tables:\n")
            for table in tables:
                print(f"  OK  {table}")
            print()

        return tables

    return []


# ============================================================
# OPTION 1: TEST CONNECTION
# ============================================================

def option_test_connection(base_url, db_config):
    test_mysql(base_url, db_config)


# ============================================================
# OPTION 2: LIST TABLES
# ============================================================

def option_list_tables(base_url, db_config):
    list_tables(base_url, db_config)


# ============================================================
# OPTION 3: INSPECT TABLE
# ============================================================

def option_inspect_table(base_url, db_config):

    tables = list_tables(base_url, db_config)

    if not tables:
        return

    print(f"Available tables: {', '.join(tables)}")
    table_name = input("\nEnter table name to inspect: ").strip()

    if not table_name:
        print_error("Table name is required.")
        return

    print_header(f"TABLE STRUCTURE: {table_name}")

    payload = {**db_config, "table": table_name}

    response = api_post(base_url, "/table-info", payload)

    if handle_api_error(response, "Table info"):
        return

    data = response.json()

    if not data.get("success"):
        print_error(data.get("detail", "Unknown error"))
        return

    columns = data.get("columns", [])

    if not columns:
        print_error("No columns found.")
        return

    print(f"\nTable: {data.get('table', table_name)}")
    print(f"Database: {data.get('database', 'unknown')}\n")

    header = f"{'Column':<30} {'Type':<40} {'Null':<6} {'Key':<6} {'Default':<20} {'Extra':<20}"
    print(header)
    print("-" * len(header))

    for col in columns:
        field = col.get("Field", "")
        col_type = col.get("Type", "")
        null_val = col.get("Null", "")
        key = col.get("Key", "")
        default = col.get("Default", "")
        extra = col.get("Extra", "")

        if default is None:
            default = "NULL"

        print(f"{field:<30} {col_type:<40} {null_val:<6} {key:<6} {str(default):<20} {extra:<20}")

    print()


# ============================================================
# OPTION 4: DATABASE INFO
# ============================================================

def option_database_info(base_url, db_config):
    print_header("DATABASE INFORMATION")

    response = api_post(base_url, "/database-info", db_config)

    if handle_api_error(response, "Database info"):
        return

    data = response.json()

    if data.get("success"):
        print(f"\n  Database      : {data.get('database', 'unknown')}")
        print(f"  MySQL Version : {data.get('mysql_version', 'unknown')}")
        print(f"  Hostname      : {data.get('hostname', 'unknown')}")
        print(f"  Current User  : {data.get('current_user', 'unknown')}")
        print()
    else:
        print_error(data.get("detail", "Unknown error"))


# ============================================================
# OPTION 5: EXECUTE SQL QUERY
# ============================================================

def print_rows_table(rows, columns):
    if not rows:
        print("No results.\n")
        return

    if not columns:
        print("No columns in result.\n")
        return

    col_widths = {}
    for col in columns:
        col_widths[col] = max(len(str(col)), 10)
    for row in rows:
        for col in columns:
            val = str(row.get(col, ""))
            if len(val) > col_widths[col]:
                col_widths[col] = min(len(val), 50)

    header = "  ".join(f"{col:<{col_widths[col]}}" for col in columns)
    print(header)
    print("-" * len(header))

    for row in rows:
        line = "  ".join(
            f"{str(row.get(col, '')):<{col_widths[col]}}"
            for col in columns
        )
        print(line)

    print()


def option_execute_query(base_url, db_config):
    print_header("EXECUTE SQL")

    print("\nAny SQL statements are allowed (development/admin use).")
    print("Separate multiple statements with ';'.")
    print("Results are capped at 100 rows per statement.\n")

    query = input("Enter SQL query: ").strip()

    if not query:
        print_error("Query cannot be empty.")
        return

    payload = {
        **db_config,
        "query": query,
        "max_rows": 100
    }

    response = api_post(base_url, "/query", payload)

    if handle_api_error(response, "Query execution"):
        return

    data = response.json()

    if not data.get("success"):
        print_error(data.get("detail", "Unknown error"))
        return

    statements = data.get("statements", [])

    if not statements:
        print("No results.\n")
        return

    for idx, stmt in enumerate(statements, start=1):
        print(f"\n--- Result {idx} ---")

        if stmt.get("type") == "RESULT":
            rows = stmt.get("rows", [])
            columns = stmt.get("columns", [])

            total = stmt.get("row_count", 0)
            returned = stmt.get("returned_rows", 0)

            if returned < total:
                print(f"Showing {returned} of {total} rows.")

            if rows:
                print_rows_table(rows, columns)
            else:
                print("No results.\n")
        else:
            affected = stmt.get("affected_rows", 0)
            msg = f"OK: {affected} row(s) affected."
            if "last_insert_id" in stmt:
                msg += f" Last insert ID: {stmt['last_insert_id']}."
            print(msg)
            print()

    print()


# ============================================================
# MAIN MENU
# ============================================================

def show_menu():
    print_header("DATABASE MENU")
    print()
    print("  1. Test MySQL connection")
    print("  2. List tables")
    print("  3. Inspect table")
    print("  4. Database information")
    print("  5. Execute SQL")
    print("  6. Exit")
    print()
    choice = input("Choose an option: ").strip()
    print()
    return choice


# ============================================================
# MAIN
# ============================================================

def main():

    base_url = get_server_config()
    db_config = get_mysql_config()

    # --------------------------------------------------------
    # STEP 1: CHECK SERVER
    # --------------------------------------------------------

    if not check_server(base_url):
        print_error("Stopping program.")
        sys.exit(1)

    # --------------------------------------------------------
    # STEP 2: TEST MYSQL
    # --------------------------------------------------------

    if not test_mysql(base_url, db_config):
        print_error("Stopping program.")
        sys.exit(1)

    # --------------------------------------------------------
    # STEP 3: LIST TABLES
    # --------------------------------------------------------

    tables = list_tables(base_url, db_config)

    # --------------------------------------------------------
    # INTERACTIVE MENU
    # --------------------------------------------------------

    while True:
        choice = show_menu()

        if choice == "1":
            option_test_connection(base_url, db_config)

        elif choice == "2":
            option_list_tables(base_url, db_config)

        elif choice == "3":
            option_inspect_table(base_url, db_config)

        elif choice == "4":
            option_database_info(base_url, db_config)

        elif choice == "5":
            option_execute_query(base_url, db_config)

        elif choice == "6":
            print_header("GOODBYE")
            print()
            sys.exit(0)

        else:
            print_error("Invalid option. Choose 1-6.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
