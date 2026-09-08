# Remote MySQL Service

Remote MySQL access over Tailscale using FastAPI.

## Architecture

```
CLIENT PC
  |
  | Tailscale (HTTP :1234)
  v
SERVER PC
  |
  | localhost:3306
  v
MySQL 8.x
```

MySQL stays bound to localhost. Only the FastAPI service is exposed through Tailscale.

## Setup

### 1. Install Python Dependencies

```bash
cd ~/Desktop/cloud_project
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. Create .env (Server PC)

```bash
cd backend
cp .env.example .env
# Edit .env with your MySQL credentials
```

### 3. Start MySQL

```bash
sudo systemctl start mysql
sudo systemctl status mysql
```

### 4. Start FastAPI Server

```bash
cd ~/Desktop/cloud_project/backend
source ../venv/bin/activate
uvicorn server_mysql:app --host 0.0.0.0 --port 1234
```

### 5. Run Client (on Client PC)

```bash
cd ~/Desktop/cloud_project/backend
source ../venv/bin/activate
python3 client_mysql.py
```

## Client PC Setup

Same Python dependencies. Copy the `backend/` directory or clone the repo.

```bash
cd ~/Desktop/cloud_project
python3 -m venv venv
source venv/bin/activate
pip install requests
```

## API Endpoints

| Method | Path             | Description                  |
|--------|------------------|------------------------------|
| GET    | /                | Health check                 |
| POST   | /test-db         | Test MySQL connection        |
| POST   | /tables          | List database tables         |
| POST   | /table-info      | Inspect table structure      |
| POST   | /database-info   | Get database information     |
| POST   | /query           | Execute SQL statements (admin use) |

## Firewall (UFW)

Allow API port only on Tailscale interface:

```bash
sudo ufw allow in on tailscale0 to any port 1234 proto tcp
```

Do NOT open port 3306.

## Security Notes

- `/query` accepts ANY SQL, including DDL and multiple `;`-separated
  statements. It is intended for development/admin use and can modify
  data. Only expose this service over a trusted Tailscale network.
- Result sets are capped at 100 rows by default (`max_rows`).
- MySQL client errors (bad syntax, wrong table/database, access denied)
  return HTTP 400; server/connection failures return HTTP 500.
- Passwords are never logged and never included in error messages.

## Systemd Service

```bash
sudo cp systemd/mysql-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mysql-api
sudo systemctl start mysql-api
sudo systemctl status mysql-api

# Logs
sudo journalctl -u mysql-api -f
```

## Testing Commands

```bash
# Health check
curl http://127.0.0.1:1234/

# Find Tailscale IP
tailscale ip

# Check server is listening
sudo ss -lntp | grep 1234

# Tailscale connectivity
tailscale status
tailscale ping <SERVER_TAILSCALE_IP>
```

## Troubleshooting

**Client cannot reach server:**
- Check Tailscale is running on both PCs: `tailscale status`
- Check server IP: `tailscale ip`
- Check Uvicorn is running on server
- Check firewall: `sudo ufw status`

**MySQL connection fails:**
- MySQL must be running: `sudo systemctl status mysql`
- MySQL binds to localhost by default (this is correct)
- Check credentials in .env
- Check database exists: `mysql -u root -p -e "SHOW DATABASES"`

**Port 1234 already in use:**
- Kill existing process: `sudo ss -lntp | grep 1234`
- Or use a different port
