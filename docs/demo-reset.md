# Demo/Beta Reset

This document describes the local reset process for Yara demo and beta testing.

The reset is for development/demo databases only. It clears old test data so a
new beta session starts from a clean state and old pending cards, payments, or
profiles do not confuse the tester.

## Safety Rules

- Never run this against production.
- The script refuses to run when `ENVIRONMENT=production` or `ENV=production`.
- The script requires `--confirm`.
- The script prints the tables and row counts before deleting data.
- The script deletes data only; it does not drop schema, migrations, or Alembic
  history.
- The script does not modify LLM logic, normalizer rules, validators, financial
  execution, reconciliation, or application runtime behavior.

## Start The Dev Environment

Use the normal development compose stack:

```bash
docker compose \
  --env-file .env.development \
  -f docker-compose.yml \
  -f docker-compose.development.yml \
  up -d
```

Verify the backend is healthy:

```bash
curl -f http://localhost:8000/health
```

## Reset Demo Data

Default reset clears project-owned data and users:

```bash
./scripts/reset-demo-data.sh --confirm
```

Preserve existing users but delete projects and project data:

```bash
./scripts/reset-demo-data.sh --confirm --keep-users
```

Reset and seed a local-only demo login/project:

```bash
./scripts/reset-demo-data.sh --confirm --seed-demo-project
```

Seeded demo credentials:

- Email: `beta@yara.local`
- Password: `password123`
- Project: `ویلا دماوند تستی`

Do not use these credentials outside local development/demo testing.

## What Gets Cleared

The script deletes rows from existing application tables in dependency order,
including:

- `interpretation_feedback`
- `trace_events`
- `trace_event_counter`
- `dead_letter_job`
- `reconciliation_event`
- `financial_migration_log`
- `shadow_interpretation_log`
- `natural_input_jobs`
- `historyentry`
- `eventcorrection`
- `payment`
- `invoice`
- `worklog`
- `workerstate`
- `pendinginterpretation`
- `extractedevent`
- `rawentry`
- `worker`
- `project`
- `users`, unless `--keep-users` is passed

Missing tables are skipped, so the script can run across local migration states
without guessing new table names.

## Database URL

The script loads `.env.development` when present. Because Docker services use
the internal host `postgres`, the script automatically rewrites:

```text
postgresql+psycopg://...@postgres:5432/...
```

to the local forwarded port from `POSTGRES_HOST_PORT`, usually:

```text
postgresql+psycopg://...@127.0.0.1:5433/...
```

To override the target database explicitly for local development, set:

```bash
RESET_DATABASE_URL=postgresql+psycopg://yara:yara_password@127.0.0.1:5433/yara_dev \
  ./scripts/reset-demo-data.sh --confirm
```

## Verify Clean State

After reset:

1. Confirm the backend still responds:

   ```bash
   curl -f http://localhost:8000/health
   ```

2. Open the frontend.
3. Sign up or log in with the seeded demo user.
4. Create or open `ویلا دماوند تستی`.
5. Confirm people, payments, work logs, reports, and pending cards are empty or
   ready for the beta checklist.
6. Start the manual scenarios in `docs/beta-scenario-checklist.md`.

## Validation

Before shipping changes to this reset process, run:

```bash
bash -n scripts/reset-demo-data.sh
backend/.venv/bin/python -m pytest backend/tests -q --tb=short
cd frontend
npm run build
```
