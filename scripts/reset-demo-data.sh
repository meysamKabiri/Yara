#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.development"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/backend/.venv/bin/python}"

CONFIRM=false
KEEP_USERS=false
SEED_DEMO_PROJECT=false

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/reset-demo-data.sh --confirm [--keep-users] [--seed-demo-project]

Safety:
  - Refuses to run when ENVIRONMENT=production.
  - Requires --confirm.
  - Deletes application/demo data only; it does not drop schema or migrations.

Options:
  --confirm             Required. Acknowledges destructive demo-data cleanup.
  --keep-users          Preserve users while deleting project-owned data.
  --seed-demo-project   Create beta@yara.local / password123 and project ویلا دماوند تستی after reset.
  --help                Show this help text.
USAGE
}

load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0

  while IFS='=' read -r key value || [[ -n "${key:-}" ]]; do
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ -z "$key" || "$key" == \#* ]] && continue
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="${value%%#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    if [[ -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done < "$file"
}

for arg in "$@"; do
  case "$arg" in
    --confirm)
      CONFIRM=true
      ;;
    --keep-users)
      KEEP_USERS=true
      ;;
    --seed-demo-project)
      SEED_DEMO_PROJECT=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage
      exit 2
      ;;
  esac
done

load_env_file "$ENV_FILE"

ENVIRONMENT_VALUE="${ENVIRONMENT:-${ENV:-local}}"
ENVIRONMENT_LOWER="$(printf '%s' "$ENVIRONMENT_VALUE" | tr '[:upper:]' '[:lower:]')"

if [[ "$ENVIRONMENT_LOWER" == "production" || "$ENVIRONMENT_LOWER" == "prod" ]]; then
  echo "Refusing to reset demo data because ENVIRONMENT=$ENVIRONMENT_VALUE." >&2
  exit 1
fi

if [[ "$CONFIRM" != "true" ]]; then
  echo "Refusing to run without explicit confirmation." >&2
  echo
  usage
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

export YARA_RESET_KEEP_USERS="$KEEP_USERS"
export YARA_RESET_SEED_DEMO_PROJECT="$SEED_DEMO_PROJECT"
export YARA_RESET_ROOT="$ROOT_DIR"

echo "Yara demo/beta reset"
echo "Environment: $ENVIRONMENT_VALUE"
echo "Env file: $ENV_FILE"
echo "Keep users: $KEEP_USERS"
echo "Seed demo project: $SEED_DEMO_PROJECT"
echo
echo "This will delete demo/beta application data from the development database."
echo "It will not drop tables, delete Alembic migrations, or modify schema."
echo

"$PYTHON_BIN" <<'PY'
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ROOT = Path(os.environ["YARA_RESET_ROOT"])
sys.path.insert(0, str(ROOT / "backend"))

KEEP_USERS = os.environ.get("YARA_RESET_KEEP_USERS", "false").lower() == "true"
SEED_DEMO_PROJECT = os.environ.get("YARA_RESET_SEED_DEMO_PROJECT", "false").lower() == "true"

DELETE_ORDER = [
    "interpretation_feedback",
    "trace_events",
    "trace_event_counter",
    "dead_letter_job",
    "reconciliation_event",
    "financial_migration_log",
    "shadow_interpretation_log",
    "natural_input_jobs",
    "historyentry",
    "eventcorrection",
    "payment",
    "invoice",
    "worklog",
    "workerstate",
    "pendinginterpretation",
    "extractedevent",
    "rawentry",
    "worker",
    "project",
]

if not KEEP_USERS:
    DELETE_ORDER.append("users")


def database_url() -> str:
    url = os.environ.get("RESET_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        url = "postgresql+psycopg://yara:yara_password@127.0.0.1:5433/yara_dev"

    host_port = os.environ.get("POSTGRES_HOST_PORT", "5433")
    url = url.replace("@postgres:5432/", f"@127.0.0.1:{host_port}/")
    return url


def ensure_not_production(url: str) -> None:
    env = (os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "local").lower()
    if env in {"production", "prod"}:
        raise SystemExit(f"Refusing to run because ENVIRONMENT={env}.")
    lowered_url = url.lower()
    production_markers = ("prod", "production")
    if any(marker in lowered_url for marker in production_markers) and "yara_dev" not in lowered_url:
        raise SystemExit("Refusing to run because DATABASE_URL looks production-like.")


def table_exists(engine: Engine, table_name: str) -> bool:
    with engine.connect() as conn:
        return conn.scalar(text("select to_regclass(:name)"), {"name": f"public.{table_name}"}) is not None


def table_count(conn, table_name: str) -> int:
    return int(conn.scalar(text(f'select count(*) from "{table_name}"')) or 0)


url = database_url()
ensure_not_production(url)
engine = create_engine(url, future=True)

existing_tables = [table for table in DELETE_ORDER if table_exists(engine, table)]
missing_tables = [table for table in DELETE_ORDER if table not in existing_tables]

print("Delete plan:")
with engine.connect() as conn:
    for table in existing_tables:
        print(f"  - {table}: {table_count(conn, table)} row(s)")

if missing_tables:
    print("Skipped missing tables:")
    for table in missing_tables:
        print(f"  - {table}")

print()
print("Running reset...")

with engine.begin() as conn:
    for table in existing_tables:
        result = conn.execute(text(f'delete from "{table}"'))
        print(f"  deleted {result.rowcount if result.rowcount is not None else '?'} from {table}")

    if SEED_DEMO_PROJECT:
        from app.core.auth import hash_password

        requested_user_id = uuid.uuid4()
        demo_user_id = conn.scalar(
            text(
                """
                insert into users (id, email, password_hash)
                values (:id, :email, :password_hash)
                on conflict (email) do update
                set password_hash = excluded.password_hash
                returning id
                """
            ),
            {
                "id": requested_user_id,
                "email": "beta@yara.local",
                "password_hash": hash_password("password123"),
            },
        )
        project_id = conn.scalar(
            text(
                """
                insert into project (owner_id, name, description)
                values (:owner_id, :name, :description)
                returning id
                """
            ),
            {
                "owner_id": demo_user_id,
                "name": "ویلا دماوند تستی",
                "description": "Local demo/beta project seeded by reset-demo-data.sh",
            },
        )
        print()
        print("Seeded local-only demo data:")
        print("  user: beta@yara.local")
        print("  password: password123")
        print(f"  project_id: {project_id}")

print()
print("Reset complete. Schema and Alembic migration history were preserved.")
PY
