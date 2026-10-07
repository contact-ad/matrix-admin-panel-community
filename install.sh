#!/bin/bash
set -Eeuo pipefail

[ "$EUID" -eq 0 ] || { echo "Run this script as root."; exit 1; }
cd "$(dirname "$0")"

echo
echo "============================================"
echo " Matrix Admin Panel Community - Installation"
echo "============================================"
echo

command -v docker >/dev/null || { echo "ERROR: docker is required."; exit 1; }
docker compose version >/dev/null || { echo "ERROR: docker compose is required."; exit 1; }

read -rp "Docker network used by Synapse: " MATRIX_NETWORK
[ -n "$MATRIX_NETWORK" ] || { echo "A Docker network is required."; exit 1; }
docker network inspect "$MATRIX_NETWORK" >/dev/null 2>&1 || {
  echo "ERROR: Docker network '$MATRIX_NETWORK' does not exist."
  exit 1
}

read -rp "Matrix server name [My Matrix]: " INSTANCE_NAME
INSTANCE_NAME=${INSTANCE_NAME:-My Matrix}

read -rp "Matrix chat domain (example: chat.example.com): " CHAT_DOMAIN
[ -n "$CHAT_DOMAIN" ] || { echo "A chat domain is required."; exit 1; }

read -rp "RTC domain, optional (example: rtc.example.com): " RTC_DOMAIN
read -rp "Synapse container name [matrix-synapse]: " SYNAPSE_CONTAINER
SYNAPSE_CONTAINER=${SYNAPSE_CONTAINER:-matrix-synapse}
docker inspect "$SYNAPSE_CONTAINER" >/dev/null 2>&1 || {
  echo "ERROR: container '$SYNAPSE_CONTAINER' not found."
  exit 1
}

read -rp "PostgreSQL container name, optional [matrix-postgres]: " POSTGRES_CONTAINER
POSTGRES_CONTAINER=${POSTGRES_CONTAINER:-matrix-postgres}

read -rp "Portal brand [Matrix Admin Panel]: " PANEL_BRAND
PANEL_BRAND=${PANEL_BRAND:-Matrix Admin Panel}
read -rp "Portal admin username [admin]: " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}

while true; do
  read -s -rp "Portal admin password (12 characters minimum): " ADMIN_PASS; echo
  read -s -rp "Confirm: " ADMIN_PASS2; echo
  [ "$ADMIN_PASS" = "$ADMIN_PASS2" ] || { echo "Passwords do not match."; continue; }
  [ ${#ADMIN_PASS} -ge 12 ] || { echo "12 characters minimum."; continue; }
  break
done

mkdir -p config data/tokens
chmod 700 data data/tokens

python3 - "$INSTANCE_NAME" "$CHAT_DOMAIN" "$RTC_DOMAIN" "$SYNAPSE_CONTAINER" "$POSTGRES_CONTAINER" <<'PY'
import json, sys
name, chat, rtc, synapse, postgres = sys.argv[1:]
data=[{
  "slug":"main",
  "name":name,
  "chat_domain":chat,
  "rtc_domain":rtc,
  "synapse_container":synapse,
  "postgres_container":postgres,
  "primary":True
}]
open("config/instances.json","w",encoding="utf-8").write(json.dumps(data,indent=2,ensure_ascii=False)+"\n")
PY

APP_SECRET=$(python3 - <<'PY'
import secrets
print(secrets.token_hex(48))
PY
)

ADMIN_HASH=$(python3 - "$ADMIN_PASS" <<'PY'
import hashlib, secrets, sys
password=sys.argv[1]
salt=secrets.token_hex(16)
digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),310000).hex()
print(f"pbkdf2_sha256${salt}${digest}")
PY
)

unset ADMIN_PASS ADMIN_PASS2

cat > .env <<EOF
APP_SECRET=$APP_SECRET
BOOTSTRAP_ADMIN_USER=$ADMIN_USER
BOOTSTRAP_ADMIN_HASH=$ADMIN_HASH
PANEL_BRAND=$PANEL_BRAND
PANEL_TITLE=Matrix Admin
MFA_ISSUER=$PANEL_BRAND
SESSION_COOKIE_SECURE=true
PANEL_PORT=8090
MATRIX_NETWORK=$MATRIX_NETWORK
INSTANCE_CONFIG=/config/instances.json
SERVICE_ADMIN_DISPLAY_NAME=Matrix Admin Service
EOF
chmod 600 .env

echo
echo "Building and starting..."
docker compose up -d --build

echo
echo "============================================"
echo " Installation complete"
echo "============================================"
echo
echo "Local listener: http://127.0.0.1:8090"
echo
echo "IMPORTANT:"
echo "  - Use HTTPS through a reverse proxy in production."
echo "  - SESSION_COOKIE_SECURE=true requires HTTPS for normal browser login."
echo "  - Read SECURITY.md before exposing this service."
echo
echo "Example Caddy block (host-installed Caddy):"
echo
echo "admin.example.com {"
echo "    reverse_proxy 127.0.0.1:8090"
echo "}"
echo
