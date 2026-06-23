# Docker Development Setup

Docker is the single source of truth for backend infrastructure **and** backend
runtime.  Only the frontend and Ollama stay on the Mac host.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Node.js (for the frontend)
- [Ollama](https://ollama.com/) running locally with the configured model

## Quick Start

```bash
# 1. Start Ollama (keep this terminal open)
ollama serve

# 2. Reset database with demo data
bash backend/scripts/reset_demo_db.sh

# 3. Start API and worker
docker compose up --build api worker

# 4. In a separate terminal, start the frontend
cd frontend && npm run dev
```

Visit http://localhost:8000/health and http://localhost:8000/projects.

## All Commands

### Database Management

| Goal                      | Command                                           |
|---------------------------|---------------------------------------------------|
| Clean reset, no demo data | `bash backend/scripts/reset_empty_db.sh`          |
| Clean reset with demo     | `bash backend/scripts/reset_demo_db.sh`           |
| Add demo data later       | `docker compose run --rm seed`                    |
| Start existing DB         | `docker compose up api worker`                    |
| Check tables              | `docker exec -it yara_postgres psql -U yara -d yara_dev -c "\dt"` |
| Check projects            | `docker exec -it yara_postgres psql -U yara -d yara_dev -c "select id, name from project;"` |

Equivalent `docker compose` commands (instead of using the scripts):

```bash
# Clean reset, no demo
docker compose down -v
docker compose up --build migrate

# Clean reset with demo
docker compose down -v
docker compose up --build migrate seed
```

### Running the stack

```bash
# Start backend (API + worker with hot-reload)
docker compose up --build api worker

# Start only infrastructure (when running API/worker locally)
docker compose up -d postgres redis
```

### Frontend (always local)

```bash
cd frontend && npm run dev
```

### Ollama (always on Mac host)

```bash
ollama serve
```

### Health checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/projects
```

## Services

### Docker services

| Service    | Container       | Host Port | Internal Port | Description              |
|------------|-----------------|-----------|---------------|--------------------------|
| PostgreSQL | `yara_postgres` | `5433`    | `5432`        | Database                 |
| Redis      | `yara_redis`    | `6380`    | `6379`        | Job queue + cache        |
| Migrate    | `yara_migrate`  | —         | —             | Runs `alembic upgrade head`, exits |
| Seed       | `yara_seed`     | —         | —             | Seeds demo data, exits   |
| API        | `yara_api`      | `8000`    | `8000`        | FastAPI server (hot-reload) |
| Worker     | `yara_worker`   | —         | —             | RQ worker for `llm_tasks` |

### Local-only services

| Service  | How to start        | URL                             |
|----------|---------------------|---------------------------------|
| Frontend | `npm run dev`       | http://localhost:5173           |
| Ollama   | `ollama serve`      | http://localhost:11434          |

## Environment Variables

Inside Docker containers the compose file sets these variables automatically:

| Variable                | Value                                           |
|-------------------------|-------------------------------------------------|
| `DATABASE_URL`          | `postgresql+psycopg://yara:yara_password@postgres:5432/yara_dev` |
| `REDIS_URL`             | `redis://redis:6379`                            |
| `OLLAMA_BASE_URL`       | `http://host.docker.internal:11434`             |
| `OLLAMA_MODEL`          | `qwen3:4b`                                      |
| `OLLAMA_TIMEOUT_SECONDS`| `15`                                            |
| `OLLAMA_NUM_PREDICT`    | `200`                                           |
| `PYTHONPATH`            | `/app`                                          |
| `PYTHONUNBUFFERED`      | `1`                                             |

For local development against Docker infrastructure use:

```bash
DATABASE_URL=postgresql+psycopg://yara:yara_password@localhost:5433/yara_dev
REDIS_URL=redis://localhost:6380
OLLAMA_BASE_URL=http://localhost:11434
```

## How it works

- **postgres** and **redis** are long-running infrastructure services with
  health checks.
- **migrate** is a one-shot service that runs `alembic upgrade head` and exits.
  It only starts after postgres is healthy.
- **seed** is a one-shot service that runs the seed script and exits.  It only
  starts after migrate has completed.
- **api** depends on postgres, redis, and migrate.  When you run
  `docker compose up api worker`, Compose ensures migrate runs first if it
  hasn't already completed.  A bind mount (`./backend:/app`) enables hot-reload
  during development.
- **worker** has the same dependencies and bind mount as api.  It listens on
  the `llm_tasks` RQ queue.
- `docker compose down -v` stops all containers and removes named volumes
  (data wiped).  No orphan state is left behind.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Docker                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Postgres │  │  Redis   │  │ Migrate  │ (one-shot) │
│  │ :5433    │  │ :6380    │  └──────────┘           │
│  └────┬─────┘  └────┬─────┘                          │
│       │              │                                │
│  ┌────▼──────────────▼─────┐  ┌──────────────────┐   │
│  │         API             │  │     Worker       │   │
│  │   (hot-reload :8000)    │  │  (RQ llm_tasks)  │   │
│  └─────────┬───────────────┘  └────────┬─────────┘   │
│            │                           │              │
└────────────┼───────────────────────────┼──────────────┘
             │                           │
    ┌────────▼────────┐       ┌──────────▼──────────┐
    │    Ollama       │       │     Frontend        │
    │  (Mac host)     │       │   (Mac host:5173)   │
    │  :11434         │       │   npm run dev       │
    └─────────────────┘       └─────────────────────┘
```
