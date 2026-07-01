# Docker Development Setup

Docker is the source of truth for Yara's development infrastructure and backend
runtime. The development compose file runs Ollama explicitly inside Docker and
the API and worker call it at `http://ollama:11434`.

## Prerequisites

- Docker Desktop
- Node.js, only when using the default local frontend workflow

## Quick Start

```bash
./start.sh
```

This starts:

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

Warm the model before a manual LLM test to avoid first-request model-load delay:

```bash
python scripts/warmup-ollama.py
```

## Daily Commands

| Goal | Command |
|---|---|
| Start the full dev environment | `./start.sh` |
| Start backend stack only | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build api worker` |
| Warm native Ollama | `python scripts/warmup-ollama.py` |
| Benchmark Ollama prompts | `python scripts/benchmark-ollama.py` |
| Reset DB, no demo data | `./reset-db.sh` |
| Stop containers | `docker compose -f docker-compose.yml -f docker-compose.dev.yml down` |
| Stop containers and wipe data | `docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v` |

Pull the local dev model into the Docker Ollama volume:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec ollama ollama pull qwen3:4b
```

Set a different model with:

```bash
OLLAMA_MODEL=your-model ./start.sh
```

## Services

| Service | Container | Host Port | Internal URL | Purpose |
|---|---|---:|---|---|
| Ollama | Docker container | `11434` | `http://ollama:11434` | Local LLM runtime |
| PostgreSQL | `yara_postgres` | `5433` | `postgres:5432` | Database |
| Redis | `yara_redis` | `6380` | `redis:6379` | Queue/cache |
| API | `yara_api` | `8000` | `http://api:8000` | FastAPI app with hot reload |
| Worker | `yara_worker` | - | - | RQ worker for `llm_tasks` |

## Health Checks

- `postgres`: `pg_isready -U yara -d yara_dev`
- `redis`: `redis-cli ping`
- `ollama`: `curl -f http://localhost:11434/api/tags`
- `api`: `curl -f http://localhost:8000/health`

## Environment

Compose injects backend environment variables automatically:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://yara:yara_password@postgres:5432/yara_dev` |
| `REDIS_URL` | `redis://redis:6379` |
| `OLLAMA_BASE_URL` | `http://ollama:11434` |
| `OLLAMA_MODEL` | `${OLLAMA_MODEL:-qwen3:4b}` |
| `OLLAMA_TIMEOUT_SECONDS` | `${OLLAMA_TIMEOUT_SECONDS:-60}` |
| `OLLAMA_NUM_PREDICT` | `${OLLAMA_NUM_PREDICT:-120}` |
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
postgres ────────────┘    ▲
    │                     │
    └─────────────────────┘
redis ────────────────────┘

api ── local Vite frontend started by ./start.sh
```

Startup rules:

- `postgres` must be healthy before `migrate` or `api`.
- `redis` must be healthy before `api` or `worker`.
- `migrate` must complete successfully before `api` or `worker`.
- Ollama should be reachable before LLM-backed manual tests.
- `api` must be healthy before `worker`.
