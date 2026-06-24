#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker compose up -d

echo ""
echo "  Yara is starting:"
echo "  API:      http://localhost:8000/health"
echo "  Ollama:   http://localhost:11434/api/tags"
echo "  Postgres: localhost:5433"
echo "  Redis:    localhost:6380"
echo ""
echo "  Migrations run automatically inside the API container on startup."
echo "  Each service retries dependencies internally."
echo ""
