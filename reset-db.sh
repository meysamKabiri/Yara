#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v

echo ""
echo "Database volumes removed. Run 'docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d' to start fresh."
echo "Migrations run automatically inside the API container."
echo ""
