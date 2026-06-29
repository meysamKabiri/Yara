#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-yara_prod}"
export PREVIOUS_IMAGE_TAG="${PREVIOUS_IMAGE_TAG:-previous}"
YARA_IMAGE="${YARA_IMAGE:-yara-backend}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

docker image inspect "${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}" >/dev/null

echo "Rolling back production to ${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}"
docker tag "${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}" "${YARA_IMAGE}:production"
IMAGE_TAG=production docker compose --env-file .env.production "${COMPOSE_FILES[@]}" up -d api worker

echo "Verifying rollback health"
BASE_URL="http://localhost:${API_HOST_PORT:-8000}" curl -fsS "http://localhost:${API_HOST_PORT:-8000}/health"

echo "Rollback complete"
