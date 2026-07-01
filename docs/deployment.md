# Yara Deployment Architecture

Yara uses one Docker service topology across every environment:

- `api`: FastAPI backend
- `worker`: RQ worker for natural-input jobs
- `postgres`: environment-owned PostgreSQL database
- `redis`: environment-owned Redis cache/queue

The same codebase is used everywhere. Environment behavior is selected
explicitly with Compose files and env files.

## Environments

Development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Staging:

```bash
scripts/deploy-staging.sh
```

Production:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d
```

## Compose Files

`docker-compose.yml` is the neutral shared base. It defines services, build
contexts, dependencies, restart policies, and health checks without env files,
ports, bind mounts, debug flags, secrets, or environment-specific defaults.

`docker-compose.dev.yml` is the explicit development environment. It adds
`.env.development`, local ports, backend bind mounts, development volumes,
development image/build args, worker command, and API hot reload.

`docker-compose.prod.yml` is the explicit production environment. It adds
`.env.production`, production persistence, production image/build args, API
port exposure, and production commands.

`docker-compose.staging.yml` adds staging env binding, staging volumes, staging host ports, and an `e2e` test service.

## Staging Flow

1. Push to `main` or `staging`.
2. `.github/workflows/staging.yml` builds the staging compose stack.
3. The workflow starts `postgres`, `redis`, `api`, and `worker`.
4. The workflow runs `python -m pytest tests/e2e` inside the compose `e2e` service.
5. The workflow validates `/health`.

Manual staging validation:

```bash
scripts/deploy-staging.sh
```

## Production Flow

Production requires explicit manual approval:

```bash
scripts/deploy-production.sh approve-production
```

The script:

1. Preserves the current `yara-backend:production` image as `yara-backend:previous`.
2. Builds the new production image.
3. Starts production containers with `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d`.
4. Runs smoke tests against:
   - `/health`
   - `/auth/login`
   - `/projects` create/list
5. Prints the point where traffic can be enabled at the load balancer or reverse proxy.

## Rollback

Rollback is one command:

```bash
scripts/rollback-production.sh
```

The rollback script:

1. Verifies `yara-backend:previous` exists.
2. Retags it as `yara-backend:production`.
3. Restarts `api` and `worker`.
4. Verifies `/health`.

## Safety Rules

- Do not reuse `.env.development`, `.env.staging`, or `.env.production` across environments.
- Do not deploy production before staging validation passes.
- Do not edit production secrets directly in git. Replace placeholder values during deployment.
- Always pass both the base compose file and the target environment compose file.
- Do not enable traffic until production smoke tests pass.
- Roll back immediately if health or smoke checks fail.
