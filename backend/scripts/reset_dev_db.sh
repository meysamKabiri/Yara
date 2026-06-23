#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
STRICT_SEED=false

for arg in "$@"; do
  case "$arg" in
    --strict-seed) STRICT_SEED=true ;;
  esac
done

echo "=== Yara Development Database Reset ==="
echo ""

# ------------------------------------------------------------------
# 1. Stop and wipe Docker volumes
# ------------------------------------------------------------------
echo "[1/6] Stopping PostgreSQL and Redis containers ..."
docker compose -f "$ROOT_DIR/docker-compose.yml" down 2>/dev/null || true

echo "[2/6] Removing Docker volumes ..."
docker volume rm yara_yara_postgres_data 2>/dev/null || true
docker volume rm yara_yara_redis_data 2>/dev/null || true

# ------------------------------------------------------------------
# 2. Start services
# ------------------------------------------------------------------
echo "[3/6] Starting PostgreSQL and Redis ..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d postgres redis

# ------------------------------------------------------------------
# 3. Wait for PostgreSQL
# ------------------------------------------------------------------
echo "[4/6] Waiting for PostgreSQL to become healthy ..."
until docker exec yara_postgres pg_isready -U yara -d yara_dev >/dev/null 2>&1; do
  printf "."
  sleep 1
done
printf " healthy\n"

# ------------------------------------------------------------------
# 4. Wait for Redis
# ------------------------------------------------------------------
echo "[5/6] Waiting for Redis to become healthy ..."
until docker exec yara_redis redis-cli ping >/dev/null 2>&1; do
  printf "."
  sleep 1
done
printf " healthy\n"

# ------------------------------------------------------------------
# 5. Run Alembic migrations
# ------------------------------------------------------------------
echo ""
echo "[6/6] Running Alembic migrations ..."
(cd "$BACKEND_DIR" && .venv/bin/alembic upgrade head)
echo ""

# ------------------------------------------------------------------
# 6. Optional seed data
# ------------------------------------------------------------------
SEED_SCRIPT="$BACKEND_DIR/dev_tools/sandbox/seed_runner.py"
if [ -f "$SEED_SCRIPT" ]; then
  echo "Seeding development data ..."
  set +e
  (
    cd "$BACKEND_DIR"
    PYTHONPATH=. .venv/bin/python dev_tools/sandbox/seed_runner.py
  )
  SEED_EXIT=$?
  set -e
  if [ $SEED_EXIT -ne 0 ]; then
    if [ "$STRICT_SEED" = true ]; then
      echo "Seed failed (exit $SEED_EXIT)"
      exit $SEED_EXIT
    else
      echo "Seed failed (exit $SEED_EXIT) — migrations still applied"
      echo "Run with --strict-seed to enforce seed success"
    fi
  else
    echo "Seed completed"
  fi
fi

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
echo ""
echo "=== Done ==="
echo ""
echo "Database reset complete.  Next steps:"
echo ""
echo "  Start the API server:"
echo "    cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000"
echo ""
echo "  Start the RQ worker (separate terminal):"
echo "    cd backend && .venv/bin/rq worker llm_tasks --url redis://localhost:6380"
echo ""
echo "  Start the frontend (separate terminal):"
echo "    cd frontend && npm run dev"
echo ""
echo "  Make sure Ollama is running locally:"
echo "    ollama serve"
echo ""
