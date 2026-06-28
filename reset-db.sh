#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker compose down -v

echo ""
echo "Database volumes removed. Run 'docker compose up -d' to start fresh."
echo "Migrations run automatically inside the API container."
echo ""
