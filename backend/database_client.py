
import mysql.connector

connection = mysql.connector.connect(
    host="100.102.221.109",  # Server's Tailscale IP
    port=3306,
    user="clouduser",
    password="your_password",
    database="cloud_db"
)

cursor = connection.cursor()

print("Connected to MySQL!")
print("Enter SQL statements ending with ';'.")
print("Type exit to quit.\n")

query = []

try:
    while True:
        line = input("SQL> " if not query else "...> ").strip()

        if not query and line.lower() in ("exit", "quit"):
            break

        query.append(line)

        if not line.endswith(";"):
            continue

        sql = "\n".join(query)
        query.clear()

        try:
            cursor.execute(sql)

            if cursor.with_rows:
                for row in cursor.fetchall():
                    print(row)
            else:
                connection.commit()
                print(f"Success! Rows affected: {cursor.rowcount}")

        except mysql.connector.Error as error:
            connection.rollback()
            print(f"MySQL Error: {error}")

except KeyboardInterrupt:
    print("\nExiting...")

finally:
    cursor.close()
    connection.close()
