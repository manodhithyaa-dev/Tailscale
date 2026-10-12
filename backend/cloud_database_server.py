import mysql.connector

connection = mysql.connector.connect(
    host="0.0.0.0",
    user="clouduser",
    password="your_password",
    database="cloud_db"
)

print("MySQL server connection successful!")