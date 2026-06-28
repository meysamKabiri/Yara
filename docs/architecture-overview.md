# Architecture Overview

## High-Level System Design

Yara is a Persian-first construction project management assistant. Users describe daily construction activity in natural Persian text ("۱۰۰ میلیون دادم به جوشکار"), and Yara extracts structured financial/work/entity events using a **dual-pipeline architecture**: a deterministic semantic rules engine (legacy) runs in parallel with an LLM v2 interpreter (shadow), with a governance engine deciding which result to use.

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React 19)                  │
│  App shell (RTL) → pages → domain modals → api.ts → fetch  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     Backend (FastAPI + Python 3.12)          │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  API Layer    │  │  RQ Worker   │  │  WebSocket Server │  │
│  │  (routers)    │  │  (async)     │  │  (job events)     │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────────┘  │
│         │                 │                                   │
│         ▼                 ▼                                   │
│  ┌──────────────────────────────────────────────────┐        │
│  │              Services Layer                       │        │
│  │  LLM Interpreter  │  Execution Engine  │  Domain │        │
│  │  Entity Registry  │  Financial Summary │  Router │        │
│  └────────────────────────┬─────────────────────────┘        │
│                           │                                   │
│                           ▼                                   │
│  ┌──────────────────────────────────────────────────┐        │
│  │              Core Layer                           │        │
│  │  Unified Pipeline  │  Governance Engine  │  Feature│       │
│  │  Financial Gate    │  Semantic Rules     │  Flags  │       │
│  │  Observability     │  Trace Context      │  Cache  │       │
│  └────────────────────────┬─────────────────────────┘        │
│                           │                                   │
│                           ▼                                   │
│  ┌──────────────────────────────────────────────────┐        │
│  │              Database (PostgreSQL)                 │        │
│  │  16+ tables: Project, Worker, Payment, WorkLog,  │        │
│  │  PendingInterpretation, NaturalInputJob, etc.    │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  External: Redis (RQ queue + pub/sub for WebSocket events)   │
│  External: Ollama (local LLM for v2 interpreter)             │
└──────────────────────────────────────────────────────────────┘
```

## Backend + Frontend Interaction

1. **REST API**: The frontend communicates via `fetch()` calls to FastAPI endpoints. All endpoints are proxied through Vite's dev server (`/api/*` → `http://localhost:8000`).

2. **WebSocket**: Job events (LLM progress, pipeline steps) are streamed in real-time via `ws://localhost:8000/ws/jobs/{job_id}` using Redis pub/sub.

3. **Polling**: When WebSocket is unavailable, the frontend falls back to polling `GET /natural-input-jobs/{id}` every 1.2s.

4. **Trace Correlation**: Every request carries a `X-Trace-Id` header propagated via ContextVar through the entire pipeline, enabling end-to-end observability.

## Domain Model

The system operates on four primary domain types:

| Domain | Enum Value | Description |
|--------|-----------|-------------|
| SETUP | `SETUP` | Entity creation/registration (workers, clients, vendors) |
| FINANCIAL | `FINANCIAL` | Payments, invoices, debts, checks, financial transactions |
| WORK | `WORK` | Work logs, daily labor tracking, task completion |
| NOTE | `NOTE` | Plain text notes, general project annotations |
| ENTITY_UPDATE | `ENTITY_UPDATE` | Profile field updates (phone, account, daily rate) |
| MIXED | `MIXED` | Combined SETUP + FINANCIAL in one input |

## Data Lifecycle

```
User Input (text)
    │
    ▼
RawEntry created (DB)
    │
    ▼
RQ Job enqueued → process_natural_input_job()
    │
    ├──→ Semantic Rule Engine (legacy, deterministic)
    │       └── Persian keyword matching → CanonicalEventType
    │
    ├──→ LLM v2 Interpreter (shadow, AI)
    │       └── Ollama API → structured JSON
    │
    ├──→ Governance Engine
    │       └── Decides LEGACY vs LLM output
    │
    ├──→ Domain Router
    │       └── Routes to SETUP / FINANCIAL / WORK / NOTE
    │
    ├──→ Execution Engine
    │       └── Writes confirmed data to DB
    │
    ├──→ PendingInterpretation created
    │       └── Awaiting user confirmation in UI
    │
    ▼
User confirms / edits / discards via UI modals
    │
    ▼
Execution Engine writes final data (Payments, WorkLogs, etc.)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend Framework | FastAPI (Python 3.12+) |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL |
| Queue | RQ (Redis Queue) |
| LLM | Ollama (local) |
| Frontend | React 19 + TypeScript + Vite |
| Styling | Plain CSS (RTL-first, 4273 lines) |
| Icons | lucide-react |
| Real-time | WebSocket via Redis pub/sub |
| Migrations | Alembic (25 revisions) |
| CLI | Click (dev_cli.py) |
