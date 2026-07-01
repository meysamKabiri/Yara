#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${SMOKE_EMAIL:-smoke@yara.local}"
PASSWORD="${SMOKE_PASSWORD:-password123}"
PROJECT_NAME="${SMOKE_PROJECT_NAME:-Smoke Test Project}"

echo "Checking health at ${BASE_URL}/health"
curl -fsS "${BASE_URL}/health" >/tmp/yara-health.json

echo "Ensuring smoke-test user exists"
curl -fsS -X POST "${BASE_URL}/auth/signup" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  >/tmp/yara-smoke-signup.json || true

echo "Logging in"
curl -fsS -X POST "${BASE_URL}/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  >/tmp/yara-smoke-login.json

TOKEN="$(
  python3 -c 'import json; print(json.load(open("/tmp/yara-smoke-login.json"))["access_token"])'
)"

echo "Creating project"
curl -fsS -X POST "${BASE_URL}/projects" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${PROJECT_NAME}\"}" \
  >/tmp/yara-smoke-project.json

echo "Listing projects"
curl -fsS "${BASE_URL}/projects" \
  -H "Authorization: Bearer ${TOKEN}" \
  >/tmp/yara-smoke-projects.json

python3 - <<'PY'
import json

projects = json.load(open("/tmp/yara-smoke-projects.json"))
if not isinstance(projects, list):
    raise SystemExit("Project list smoke check failed")
print("Smoke tests passed")
PY
