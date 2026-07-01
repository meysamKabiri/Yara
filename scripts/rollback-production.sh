#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-yara_prod}"
export PREVIOUS_IMAGE_TAG="${PREVIOUS_IMAGE_TAG:-previous}"
YARA_IMAGE="${YARA_IMAGE:-yara-backend}"

docker image inspect "${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}" >/dev/null

echo "Rolling back production to ${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}"
docker tag "${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}" "${YARA_IMAGE}:production"
IMAGE_TAG=production docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d api worker

echo "Verifying rollback health"
BASE_URL="http://localhost:8000" curl -fsS "http://localhost:8000/health"

echo "Rollback complete"
