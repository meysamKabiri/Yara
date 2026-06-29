# Yara Deployment Architecture

Yara uses one Docker service topology across every environment:

- `api`: FastAPI backend
- `worker`: RQ worker for natural-input jobs
- `postgres`: environment-owned PostgreSQL database
- `redis`: environment-owned Redis cache/queue

The same codebase is used everywhere. Environment behavior comes only from compose overlays and env files.

## Environments

Development:

```bash
docker compose --env-file .env.development -f docker-compose.yml -f docker-compose.development.yml up --build
```

Staging:

```bash
scripts/deploy-staging.sh
```

Production:

```bash
scripts/deploy-production.sh approve-production
```

## Compose Files

`docker-compose.yml` is the shared base. It defines the identical service structure, health checks, commands, and shared backend environment.

`docker-compose.development.yml` adds local development bind mounts, ports, and development volumes.

`docker-compose.staging.yml` adds staging env binding, staging volumes, staging host ports, and an `e2e` test service.

`docker-compose.prod.yml` adds production env binding, production volumes, production host port exposure, and production restart policy.

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
3. Starts production containers.
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
- Do not enable traffic until production smoke tests pass.
- Roll back immediately if health or smoke checks fail.
