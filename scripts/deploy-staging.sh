#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-yara_staging}"
export IMAGE_TAG="${IMAGE_TAG:-staging-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.staging.yml)

echo "Building staging image: ${YARA_IMAGE:-yara-backend}:${IMAGE_TAG}"
docker compose --env-file .env.staging "${COMPOSE_FILES[@]}" build

echo "Starting staging stack"
docker compose --env-file .env.staging "${COMPOSE_FILES[@]}" up -d postgres redis api worker

echo "Running staging E2E suite"
docker compose --env-file .env.staging "${COMPOSE_FILES[@]}" --profile test run --rm e2e

echo "Running staging smoke tests"
BASE_URL="http://localhost:${API_HOST_PORT:-18080}" scripts/smoke-test.sh

echo "Staging deployment validated"
