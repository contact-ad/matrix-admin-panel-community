#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$0")"

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="./backups/$STAMP"
mkdir -p "$BACKUP_DIR"

if [ -f data/portal.db ]; then
  cp -a data/portal.db "$BACKUP_DIR/"
fi
if [ -d data/tokens ]; then
  cp -a data/tokens "$BACKUP_DIR/"
fi

echo "Backup created in: $BACKUP_DIR"
docker compose up -d --build
docker compose ps
echo
echo "Upgrade/rebuild complete."
