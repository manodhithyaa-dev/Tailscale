import requests

SERVER = "http://100.102.221.109:8000"  # Replace with server's Tailscale IP

path = input("File path: ")

with open(path, "rb") as f:
    response = requests.post(
        f"{SERVER}/{path.split('/')[-1]}",
        data=f
    )

print(response.text)
