#!/usr/bin/env bash
set -euo pipefail

APPROVAL="${1:-}"
if [ "${APPROVAL}" != "approve-production" ]; then
  echo "Manual approval required."
  echo "Usage: scripts/deploy-production.sh approve-production"
  exit 2
fi

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-yara_prod}"
export IMAGE_TAG="${IMAGE_TAG:-production-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
export PREVIOUS_IMAGE_TAG="${PREVIOUS_IMAGE_TAG:-previous}"
YARA_IMAGE="${YARA_IMAGE:-yara-backend}"

if docker image inspect "${YARA_IMAGE}:production" >/dev/null 2>&1; then
  echo "Preserving previous production image as ${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}"
  docker tag "${YARA_IMAGE}:production" "${YARA_IMAGE}:${PREVIOUS_IMAGE_TAG}"
fi

echo "Building production image: ${YARA_IMAGE}:${IMAGE_TAG}"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production build
docker tag "${YARA_IMAGE}:${IMAGE_TAG}" "${YARA_IMAGE}:production"

echo "Deploying production containers"
IMAGE_TAG=production docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d

echo "Running production smoke tests"
BASE_URL="http://localhost:8000" scripts/smoke-test.sh

echo "Production smoke tests passed. Enable traffic at the load balancer/reverse proxy."
