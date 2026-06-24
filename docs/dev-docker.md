# Docker Development Setup

Docker is the source of truth for Yara's development infrastructure and backend
runtime. Ollama now runs inside the Compose network, so the API and worker call
it at `http://ollama:11434`.

## Prerequisites

- Docker Desktop
- Node.js, only when using the default local frontend workflow

## Quick Start

```bash
./start.sh
```

This starts:

- Ollama
- PostgreSQL
- Redis
- one-shot database migrations
- FastAPI with hot reload
- RQ worker
- Vite frontend on the host

Open:

- Frontend: http://localhost:5173
- API health: http://localhost:8000/health
- Ollama tags: http://localhost:11434/api/tags

## Daily Commands

| Goal | Command |
|---|---|
| Start the full dev environment | `./start.sh` |
| Start backend stack only | `docker compose up --build api worker` |
| Start fully dockerized stack | `docker compose --profile frontend up --build api worker frontend` |
| Reset DB, no demo data | `./reset-db.sh` |
| Seed demo data | `./seed-demo.sh` |
| Reset DB and seed demo data | `./reset-db.sh && ./seed-demo.sh` |
| Stop containers | `docker compose down` |
| Stop containers and wipe data | `docker compose down -v` |

If the configured model has not been pulled into the Docker Ollama volume yet:

```bash
docker compose exec ollama ollama pull qwen3:4b
```

Set a different model with:

```bash
OLLAMA_MODEL=your-model ./start.sh
```

## Services

| Service | Container | Host Port | Internal URL | Purpose |
|---|---|---:|---|---|
| Ollama | `yara_ollama` | `11434` | `http://ollama:11434` | Local LLM runtime |
| PostgreSQL | `yara_postgres` | `5433` | `postgres:5432` | Database |
| Redis | `yara_redis` | `6380` | `redis:6379` | Queue/cache |
| Migrate | `yara_migrate` | - | - | Runs `alembic upgrade head`, exits |
| Seed | `yara_seed` | - | - | Seeds demo data, exits |
| API | `yara_api` | `8000` | `http://api:8000` | FastAPI app with hot reload |
| Worker | `yara_worker` | - | - | RQ worker for `llm_tasks` |
| Frontend | `yara_frontend` | `5173` | `http://frontend:5173` | Optional Dockerized Vite dev server |

## Health Checks

- `postgres`: `pg_isready -U yara -d yara_dev`
- `redis`: `redis-cli ping`
- `ollama`: `ollama list`, equivalent readiness for `/api/tags`
- `api`: `curl -f http://localhost:8000/health`

## Environment

Compose injects backend environment variables automatically:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://yara:yara_password@postgres:5432/yara_dev` |
| `REDIS_URL` | `redis://redis:6379` |
| `OLLAMA_BASE_URL` | `http://ollama:11434` |
| `OLLAMA_MODEL` | `${OLLAMA_MODEL:-qwen3:4b}` |
| `OLLAMA_TIMEOUT_SECONDS` | `${OLLAMA_TIMEOUT_SECONDS:-15}` |
| `OLLAMA_NUM_PREDICT` | `${OLLAMA_NUM_PREDICT:-200}` |
| `OLLAMA_TEMPERATURE` | `${OLLAMA_TEMPERATURE:-0}` |

For running the backend directly on the host against Docker infrastructure, use
the values in `backend/.env.example`:

```bash
DATABASE_URL=postgresql+psycopg://yara:yara_password@localhost:5433/yara_dev
REDIS_URL=redis://localhost:6380
OLLAMA_BASE_URL=http://localhost:11434
```

## Dependency Graph

```text
ollama ──────────────┐
                     ├── api ── worker
postgres ── migrate ─┘    ▲
    │                     │
    └─────────────────────┘
redis ────────────────────┘

api ── optional dockerized frontend
api ── local Vite frontend started by ./start.sh
```

Startup rules:

- `postgres` must be healthy before `migrate` or `api`.
- `redis` must be healthy before `api` or `worker`.
- `migrate` must complete successfully before `api` or `worker`.
- `ollama` must be healthy before `api` or `worker`.
- `api` must be healthy before `worker`.
- The optional Dockerized frontend waits for `api`.
