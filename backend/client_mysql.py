import requests

SERVER = "http://100.87.123.45:8000"


def check_server():

    response = requests.get(
        f"{SERVER}/health",
        timeout=5
    )

    response.raise_for_status()

    return response.json()


def get_users():

    response = requests.get(
        f"{SERVER}/users",
        timeout=5
    )

    response.raise_for_status()

    return response.json()


def create_user(name, email):

    response = requests.post(
        f"{SERVER}/users",
        json={
            "name": name,
            "email": email
        },
        timeout=5
    )

    response.raise_for_status()

    return response.json()


if __name__ == "__main__":

    print("Checking server...")

    print(check_server())

    print("\nUsers:")

    users = get_users()

    for user in users:
        print(user)

    print("\nCreating user...")

    result = create_user(
        "Mano",
        "mano@example.com"
    )

    print(result)