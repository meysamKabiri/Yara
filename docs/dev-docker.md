# Docker Infrastructure for Local Development

PostgreSQL and Redis run in Docker.  The API server, RQ worker, and frontend
run natively for fast iteration.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.12+ with `.venv` set up in `backend/`
- Node.js (for the frontend)
- [Ollama](https://ollama.com/) running locally with the configured model

## Quick Start (first time)

```bash
# 1. Start infrastructure
cd /path/to/yara
docker compose up -d postgres redis

# 2. Run migrations
cd backend
cp .env.example .env
source .venv/bin/activate
alembic upgrade head

# 3. Start the API server
uvicorn app.main:app --reload --port 8000

# 4. In a separate terminal, start the RQ worker
cd backend
source .venv/bin/activate
rq worker llm_tasks --url redis://localhost:6380

# 5. In another terminal, start the frontend
cd frontend
npm run dev

# 6. Make sure Ollama is running
ollama serve
```

## Database Reset

Wipes all data and re-runs migrations from scratch:

```bash
bash backend/scripts/reset_dev_db.sh
```

This will:
1. Stop `postgres` and `redis` containers
2. Remove their named volumes (data is lost)
3. Start containers again
4. Wait for both to become healthy
5. Run `alembic upgrade head`
6. Optionally run the seed script

The seed script runs from `backend/` with `PYTHONPATH=.` so it can
import `app.*` and `dev_tools.*` packages.  If seeding fails the
migrations are still applied — the reset is not blocked.

To enforce seed success (exit non-zero on seed failure):

```bash
bash backend/scripts/reset_dev_db.sh --strict-seed
```

## Service Details

| Service    | Container       | Host Port | Credentials                          |
|------------|-----------------|-----------|--------------------------------------|
| PostgreSQL | `yara_postgres` | `5433`    | `yara` / `yara_password` / `yara_dev` |
| Redis      | `yara_redis`    | `6380`    | —                                    |

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and adjust as needed:

| Variable                | Default                                    | Description            |
|-------------------------|--------------------------------------------|------------------------|
| `DATABASE_URL`          | `postgresql+psycopg://yara:yara_password@localhost:5433/yara_dev` | PostgreSQL connection  |
| `REDIS_URL`             | `redis://localhost:6380`                   | Redis connection       |
| `OLLAMA_BASE_URL`       | `http://localhost:11434`                   | Ollama endpoint        |
| `OLLAMA_MODEL`          | `qwen3:4b`                                 | LLM model name         |
| `OLLAMA_TIMEOUT_SECONDS`| `15`                                       | LLM request timeout    |
| `OLLAMA_NUM_PREDICT`    | `200`                                      | Max generated tokens   |

> **Note**: `OLLAMA_BASE_URL` is documented here for reference.  The current
> backend reads Ollama settings from `OLLAMA_URL` (hardcoded in
> `llm_extraction.py`) and the individual `OLLAMA_*` environment variables
> (in `llm_v2_interpreter.py`).  Future phases will centralise these.

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   FastAPI    │    │  RQ Worker   │    │  Frontend    │
│  (host:8000) │    │  (host: RQ)  │    │ (host:5173)  │
└──┬───────────┘    └──┬───────────┘    └──────┬───────┘
   │                   │                        │
   ├──── PostgreSQL ───┤                        │
   │   (docker:5433)   │                        │
   ├──── Redis ────────┤                        │
   │   (docker:6380)   │                        │
   │                   │                        │
   └──── Ollama ───────┘                        │
       (host:11434)                             │
                                                │
                                       (browser → dev server)
```
