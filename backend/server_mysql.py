import logging
import re
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger("mysql-api")

# Quiet the mysql-connector's internal verbose logging
logging.getLogger("mysql.connector").setLevel(logging.WARNING)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Remote MySQL Service",
    description="Controlled MySQL access over Tailscale",
    version="1.0.0"
)


# ============================================================
# MIDDLEWARE - REQUEST LOGGING
# ============================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
    return response


# ============================================================
# DATA MODELS
# ============================================================

class DatabaseConfig(BaseModel):
    host: str = Field(default="127.0.0.1", description="MySQL host")
    port: int = Field(default=3306, description="MySQL port")
    user: str = Field(description="MySQL username")
    password: str = Field(description="MySQL password")
    database: str = Field(description="MySQL database name")


class TableInfoRequest(DatabaseConfig):
    table: str = Field(description="Table name to inspect")


class QueryRequest(DatabaseConfig):
    query: str = Field(description="SQL to execute (one or more statements)")
    max_rows: int = Field(default=100, ge=1, le=1000, description="Maximum rows to return per result set")


# ============================================================
# HELPER - CONNECT TO MYSQL
# ============================================================

def get_connection(config: DatabaseConfig) -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connection_timeout=10
    )


# ============================================================
# ENDPOINT: GET /
# ============================================================

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Remote MySQL Service"
    }


# ============================================================
# ENDPOINT: POST /test-db
# ============================================================

@app.post("/test-db")
def test_database(config: DatabaseConfig):

    connection = None
    cursor = None

    try:
        logger.info(f"Test DB request for user='{config.user}' database='{config.database}'")

        connection = get_connection(config)

        cursor = connection.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]

        logger.info(f"Test DB success for database='{config.database}'")

        return {
            "success": True,
            "message": "MySQL connection successful",
            "database": config.database,
            "mysql_version": version
        }

    except Error as e:
        logger.error(f"MySQL error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"MySQL connection failed: {str(e)}"
        )

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


# ============================================================
# ENDPOINT: POST /tables
# ============================================================

@app.post("/tables")
def get_tables(config: DatabaseConfig):

    connection = None
    cursor = None

    try:
        logger.info(f"List tables for database='{config.database}'")

        connection = get_connection(config)

        cursor = connection.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]

        logger.info(f"Found {len(tables)} tables in '{config.database}'")

        return {
            "success": True,
            "database": config.database,
            "tables": tables
        }

    except Error as e:
        logger.error(f"MySQL error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get tables: {str(e)}"
        )

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


# ============================================================
# HELPER - VALIDATE TABLE NAME
# ============================================================

def validate_table_name(table_name: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_]+$', table_name))


# ============================================================
# ENDPOINT: POST /table-info
# ============================================================

@app.post("/table-info")
def get_table_info(config: TableInfoRequest):

    connection = None
    cursor = None

    try:
        if not validate_table_name(config.table):
            raise HTTPException(
                status_code=400,
                detail="Invalid table name. Only alphanumeric and underscore allowed."
            )

        logger.info(f"Table info for table='{config.table}' database='{config.database}'")

        connection = get_connection(config)

        cursor = connection.cursor(dictionary=True)
        cursor.execute("DESCRIBE `%s`" % config.table)
        columns = cursor.fetchall()

        logger.info(f"Table info success for table='{config.table}'")

        return {
            "success": True,
            "database": config.database,
            "table": config.table,
            "columns": columns
        }

    except HTTPException:
        raise

    except Error as e:
        logger.error(f"MySQL error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get table info: {str(e)}"
        )

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


# ============================================================
# ENDPOINT: POST /database-info
# ============================================================

@app.post("/database-info")
def database_info(config: DatabaseConfig):

    connection = None
    cursor = None

    try:
        logger.info(f"Database info for database='{config.database}'")

        connection = get_connection(config)

        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT VERSION() AS mysql_version")
        version_row = cursor.fetchone()

        cursor.execute("SELECT DATABASE() AS database_name")
        db_row = cursor.fetchone()

        cursor.execute("SELECT USER() AS current_user")
        user_row = cursor.fetchone()

        cursor.execute("SELECT @@hostname AS hostname")
        host_row = cursor.fetchone()

        logger.info(f"Database info success for '{config.database}'")

        return {
            "success": True,
            "database": db_row["database_name"],
            "mysql_version": version_row["mysql_version"],
            "hostname": host_row["hostname"],
            "current_user": user_row["current_user"]
        }

    except Error as e:
        logger.error(f"MySQL error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database information failed: {str(e)}"
        )

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


# ============================================================
# HELPER - MAP MYSQL ERRORS TO HTTP STATUS
# ============================================================

# Client-side MySQL errors -> HTTP 400. Server/connection failures -> HTTP 500.
MYSQL_CLIENT_ERRORS = {
    1044, 1045, 1049, 1050, 1054, 1060, 1062, 1064, 1065,
    1091, 1136, 1142, 1146, 1242, 1292, 1366, 1406, 1451, 1452
}


def http_status_for_mysql_error(err: Error, default: int = 500) -> int:
    if getattr(err, "errno", None) in MYSQL_CLIENT_ERRORS:
        return 400
    return default


# ============================================================
# ENDPOINT: POST /query
# ============================================================
# Accepts ANY SQL: SELECT, INSERT, UPDATE, DELETE, DDL, and
# multiple statements separated by ';'.
# Intended for development/admin use over a trusted Tailscale network.
# Row results are capped at max_rows (default 100) per result set.

@app.post("/query")
def execute_query(config: QueryRequest):

    connection = None
    cursor = None

    try:
        query = config.query.strip().rstrip(";").strip()

        if not query:
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )

        logger.info(f"Executing query for database='{config.database}' (max_rows={config.max_rows})")

        connection = get_connection(config)
        cursor = connection.cursor(buffered=True, dictionary=True)

        cursor.execute(query)

        statements = []
        statement_no = 0

        while True:
            statement_no += 1

            if cursor.with_rows:
                columns = [d[0] for d in cursor.description] if cursor.description else []
                all_rows = cursor.fetchall()
                returned = min(len(all_rows), config.max_rows)

                statements.append({
                    "type": "RESULT",
                    "columns": columns,
                    "row_count": len(all_rows),
                    "returned_rows": returned,
                    "rows": all_rows[:returned]
                })

                logger.info(f"Statement {statement_no}: RESULT ({len(all_rows)} rows)")
            else:
                entry = {
                    "type": "OK",
                    "affected_rows": cursor.rowcount or 0
                }
                if cursor.lastrowid is not None:
                    entry["last_insert_id"] = cursor.lastrowid

                statements.append(entry)

                logger.info(f"Statement {statement_no}: OK ({cursor.rowcount} row(s) affected)")

            if cursor.nextset() is None:
                break

        logger.info(f"Query complete: {statement_no} statement(s)")

        return {
            "success": True,
            "database": config.database,
            "max_rows": config.max_rows,
            "statements": statements
        }

    except HTTPException:
        raise

    except Error as e:
        logger.error(f"MySQL error: {e}")
        raise HTTPException(
            status_code=http_status_for_mysql_error(e),
            detail=f"Query failed: {str(e)}"
        )

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=1234)
