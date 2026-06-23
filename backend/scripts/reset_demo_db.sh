#!/usr/bin/env bash
# reset_demo_db.sh — Wipes all data, runs migrations, and seeds demo data.
set -euo pipefail

cd "$(dirname "$0")/../.."

docker compose down -v
docker compose up --build migrate seed
echo ""
echo "Demo DB ready. Tables exist, seeded project available."
