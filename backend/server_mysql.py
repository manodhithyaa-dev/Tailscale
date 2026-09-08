import os
import mysql.connector
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="MySQL Service")


# -----------------------------
# MySQL configuration
# -----------------------------

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "appuser",
    "password": "YOUR_MYSQL_PASSWORD",
    "database": "your_database",
}


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


# -----------------------------
# Health check
# -----------------------------

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "mysql-service"
    }


@app.get("/health")
def health():
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()

        cursor.close()
        db.close()

        return {
            "status": "healthy",
            "mysql": "connected"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"MySQL connection failed: {str(e)}"
        )


# -----------------------------
# Example query
# -----------------------------

@app.get("/users")
def get_users():

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users")

        users = cursor.fetchall()

        cursor.close()
        db.close()

        return users

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# -----------------------------
# Example insert
# -----------------------------

class User(BaseModel):
    name: str
    email: str


@app.post("/users")
def create_user(user: User):

    try:
        db = get_db()
        cursor = db.cursor()

        query = """
            INSERT INTO users (name, email)
            VALUES (%s, %s)
        """

        cursor.execute(
            query,
            (user.name, user.email)
        )

        db.commit()

        user_id = cursor.lastrowid

        cursor.close()
        db.close()

        return {
            "success": True,
            "id": user_id
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )