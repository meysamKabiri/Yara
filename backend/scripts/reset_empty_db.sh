#!/usr/bin/env bash
# reset_empty_db.sh — Wipes all data and runs migrations with no seed data.
set -euo pipefail

cd "$(dirname "$0")/../.."

docker compose down -v
docker compose up --build migrate
echo ""
echo "Empty DB ready. Tables exist, project count = 0."
