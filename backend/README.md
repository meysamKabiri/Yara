# Yara Backend

FastAPI backend foundation for Yara Phase 1. This scaffold intentionally contains no business entities yet.

## Structure

- `app/main.py`: FastAPI application factory and router registration.
- `app/api/`: API routers, starting with health checks.
- `app/core/`: application settings loaded from environment variables.
- `app/db/`: SQLAlchemy engine, sessions, declarative base, and model conventions.
- `app/dependencies/`: FastAPI dependency providers.
- `app/models/`, `app/schemas/`, `app/services/`, `app/repositories/`: reserved boundaries for future phases.
- `alembic/`: migration environment and generated revisions.
- `tests/`: pytest tests.

## Local Setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Create a local PostgreSQL database named `yara`, then update `DATABASE_URL` in `.env` if needed.

## Run Locally

```bash
cd backend
fastapi dev app/main.py
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Verification

```bash
cd backend
ruff check .
pytest
```

## Migrations

Alembic reads `DATABASE_URL` from the same settings as the app.

Create a future migration after adding models:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```bash
cd backend
alembic upgrade head
```
