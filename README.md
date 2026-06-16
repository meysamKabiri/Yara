# Yara

Yara is a Persian-first financial notebook for small contractors.

Phase 1 goal:

Turn messy contractor notes into confirmed financial records.

Core MVP flow:

Project → Raw Note → Pending Extracted Events → Confirm/Edit/Discard → Project Totals

## Backend

The Phase 1 backend foundation lives in `backend/` and uses FastAPI, PostgreSQL,
SQLAlchemy 2.x, Alembic, Pydantic v2, and Python 3.12+.

See `backend/README.md` for local setup, verification commands, and migration workflow.

## Frontend

The minimal Phase 1 MVP frontend lives in `frontend/` and uses React,
TypeScript, and Vite.

See `frontend/README.md` for local setup and build commands.
