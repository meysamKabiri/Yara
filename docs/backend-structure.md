# Backend Structure

## Directory Layout

```
backend/
├── app/
│   ├── main.py                  # FastAPI app factory, lifespan, middleware, router registration
│   ├── api/                     # API route modules
│   │   ├── health.py            # GET /health (DB, Redis, Ollama checks)
│   │   ├── projects.py          # ~4746 lines — ALL business endpoints (CRUD, pipeline, exports)
│   │   ├── job_websockets.py    # WebSocket /ws/jobs/{job_id} for real-time job events
│   │   ├── traces.py            # GET /traces for observability queries
│   │   ├── shadow_analytics.py  # GET /shadow-analytics for migration analytics
│   │   ├── shadow_migration.py  # GET /shadow-migration for decision status
│   │   ├── financial_migration.py # GET /financial-migration/status
│   │   ├── metrics.py           # Prometheus-style metrics
│   │   └── sandbox.py           # Sandbox data seeding
│   ├── models/
│   │   └── core.py              # All 16 SQLAlchemy ORM models + StrEnum types (~448 lines)
│   ├── schemas/
│   │   ├── health.py            # Health response Pydantic models
│   │   ├── projects.py          # Request/response schemas for all business endpoints
│   │   └── llm_v2.py            # LLM v2 request/response models
│   ├── services/                # Business logic layer (23 modules)
│   │   ├── llm_v2_interpreter.py        # Ollama-based LLM interpreter
│   │   ├── llm_v2_validator.py          # LLM output validation
│   │   ├── llm_extraction.py            # Legacy extraction engine
│   │   ├── domain_router_service.py     # Domain routing logic (SETUP/FINANCIAL/WORK)
│   │   ├── execution_engine.py          # Single source of truth for confirmed writes
│   │   ├── entity_resolution_service.py # Entity resolution (fuzzy matching)
│   │   ├── entity_registry.py           # SETUP action execution
│   │   ├── entity_normalizer.py         # Name normalization utilities
│   │   ├── identity_key.py              # Composite identity key generation
│   │   ├── persian_money_engine.py      # Persian number parsing
│   │   ├── persian_role_extractor.py    # Persian role phrase mapping
│   │   ├── persian_project_payment.py   # Payment detection from Persian text
│   │   ├── semantic_normalizer.py       # Persian text normalization
│   │   ├── compare_legacy_vs_shadow.py  # Field-by-field comparison
│   │   ├── execution_comparator.py      # Execution result comparison
│   │   ├── shadow_analytics_service.py  # Shadow vs legacy analytics
│   │   ├── shadow_migration_decision_engine.py # Weighted migration readiness scoring
│   │   ├── shadow_conflict_analyzer.py  # Conflict classification
│   │   ├── shadow_logger.py             # Shadow comparison logging
│   │   ├── financial_migration_gate.py  # Safety gate for LLM financial writes
│   │   ├── financial_migration_logger.py # Migration decision logging
│   │   ├── financial_summary.py         # Financial summary computation
│   │   └── reporting_service.py         # CSV/PDF report generation
│   ├── core/                    # Core infrastructure
│   │   ├── unified_pipeline.py          # ~2415 lines — Central orchestrator
│   │   ├── config.py                    # Settings from env vars
│   │   ├── queue.py                     # Redis connection + RQ queue
│   │   ├── trace_context.py             # ContextVar trace/job ID propagation
│   │   ├── event_tracker.py             # TraceEvent DB writer
│   │   ├── logger.py                    # Logging configuration
│   │   ├── feature_flags.py             # Financial migration modes (OFF/SHADOW_ONLY/A_B_TEST/LLM_PRIMARY)
│   │   ├── llm_cache.py                 # In-memory LRU cache for LLM v2
│   │   ├── llm_authority_controller.py  # Alternative migration controller
│   │   ├── financial_role_repair.py     # Role/field repair for migration
│   │   ├── observability_schema.py      # Trace event Pydantic models
│   │   ├── observability_service.py     # Observability recording/querying
│   │   └── observability_validator.py   # Trace data integrity validation
│   │   ├── governance/
│   │   │   ├── governance_context_builder.py    # Governance context from project state
│   │   │   └── unified_governance_engine.py     # Migration governance decisions
│   │   ├── observability/
│   │   │   ├── decision_logger.py       # Governance decision audit trail
│   │   │   └── performance_logger.py    # Pipeline performance metrics
│   │   ├── runtime/
│   │   │   └── request_cache.py         # Request-scoped cache
│   │   ├── semantic_rules/
│   │   │   ├── semantic_rule_engine.py  # ~650 lines — Deterministic keyword engine
│   │   │   ├── conflict_detector.py     # Rule conflict detection
│   │   │   └── explainability.py        # Rule match explanations
│   │   └── validation/
│   │       └── financial_validator.py   # Financial safety checks
│   ├── db/
│   │   ├── base.py                      # SQLAlchemy Base + TimestampMixin
│   │   └── session.py                   # Session factory (async + sync)
│   ├── dependencies/
│   │   └── database.py                  # FastAPI get_db() dependency
│   ├── jobs/
│   │   └── natural_input_job.py         # RQ job: process_natural_input_job()
│   ├── repositories/                    # Empty (DB access is inline in services)
│   └── scripts/
│       ├── run_migrations.py            # Alembic migration runner
│       └── start_worker.py              # RQ worker entry point
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                        # 25 migration revisions
├── tests/                               # ~35 test files
│   ├── conftest.py
│   ├── mocks/
│   └── test_*.py
├── dev_tools/
│   ├── semantic_firewall/               # Semantic rule testing framework
│   └── sandbox/                         # Sandbox data generation
├── pyproject.toml
├── alembic.ini
├── Dockerfile
└── README.md (~1000+ lines)
```

## API Endpoints (Grouped by Domain)

### Projects
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/projects` | List projects (with search/filter) |
| POST | `/projects` | Create project |
| PATCH | `/projects/{id}` | Update project |
| GET | `/projects/{id}` | Get project detail with summary |

### Workers / People
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/projects/{id}/workers` | List workers |
| POST | `/projects/{id}/workers` | Create worker |
| PATCH | `/workers/{id}` | Update worker profile |
| GET | `/projects/{id}/worker-states` | List worker states |

### Natural Input (Core Pipeline)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/projects/{id}/natural-input` | Submit Persian text for AI processing |
| GET | `/natural-input-jobs/{id}` | Poll job status |
| GET | `/projects/{id}/raw-entries` | List raw entries |
| POST | `/projects/{id}/raw-entries` | Create raw entry |
| GET | `/projects/{id}/pending-interpretations` | List pending interpretations |
| PATCH | `/pending-interpretations/{id}` | Update pending interpretation |
| POST | `/pending-interpretations/{id}/confirm` | Confirm pending interpretation |
| POST | `/pending-interpretations/{id}/discard` | Discard pending interpretation |

### Financial
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/projects/{id}/payments` | List payments |
| POST | `/projects/{id}/payments` | Create payment |
| PATCH | `/projects/{id}/payments/{id}` | Correct payment |
| POST | `/projects/{id}/payments/{id}/void` | Void payment |
| GET | `/projects/{id}/invoices` | List invoices |
| POST | `/projects/{id}/invoices` | Create invoice |
| GET | `/projects/{id}/operating-summary` | Get operating summary |
| PATCH | `/projects/{id}/payables/{id}` | Correct payable |
| POST | `/projects/{id}/payables/{id}/void` | Void payable |

### Work Logs
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/projects/{id}/work-logs` | List work logs |
| POST | `/projects/{id}/work-logs` | Create work log |
| PATCH | `/projects/{id}/work-logs/{id}` | Correct work log |
| POST | `/projects/{id}/work-logs/{id}/void` | Void work log |

### History & Notes
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/projects/{id}/history` | List history entries |
| PATCH | `/projects/{id}/notes/{id}` | Correct note |
| POST | `/projects/{id}/notes/{id}/void` | Void note |

### Reports & Exports
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/projects/{id}/reports/summary` | Get project report summary |
| Various | `/projects/{id}/exports/*` | CSV exports (payments, work-logs, people, etc.) |

### Observability
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/traces/{id}` | Get trace detail |
| GET | `/metrics/trace/{id}` | Get trace metrics |
| GET | `/jobs` | List all jobs |
| GET | `/jobs/{id}/events` | List job events |
| WS | `/ws/jobs/{id}` | Real-time job event stream |
| GET | `/shadow-analytics` | Shadow migration analytics |
| GET | `/shadow-migration` | Migration decision status |
| GET | `/financial-migration/status` | Migration mode status |
| GET | `/health` | Health check (DB, Redis, Ollama) |
| GET | `/metrics` | Prometheus metrics |

## Services Explanation

### LLM v2 Interpreter (`services/llm_v2_interpreter.py`)
- Sends Persian input to Ollama with a structured system prompt
- Temperature=0 for deterministic output
- Returns structured JSON with entities, amounts, directions
- Retry logic (2 retries, 60s timeout)
- Falls back to semantic rules on failure
- Integrates observability trace events

### Domain Router (`services/domain_router_service.py`)
- Routes interpreted input into domain pipelines: SETUP, FINANCIAL, WORK, MIXED, ENTITY_UPDATE
- Maps semantic actions to UI schemas
- No business execution — pure routing

### Execution Engine (`services/execution_engine.py`)
- **Single source of truth** for confirmed financial/event writes
- Creates/updates Payments, WorkLogs, Invoices, WorkerStates
- No re-interpretation, no LLM involvement
- Enforces direction, state machine consistency

### Semantic Rule Engine (`core/semantic_rules/semantic_rule_engine.py`)
- ~60+ deterministic Persian keyword-based rules
- Classifies events as SETUP/WORK/FINANCIAL/NOTE
- Extracts entity names, amounts, directions, units
- Priority-based conflict detection

### Financial Migration Gate (`services/financial_migration_gate.py`)
- Validates LLM safety before allowing financial writes
- Compares legacy vs shadow outputs
- Enforces migration mode: OFF / SHADOW_ONLY / A_B_TEST / LLM_PRIMARY

## Database Models Overview

| Model | Table | Key Fields |
|-------|-------|------------|
| Project | `project` | id, name, description |
| RawEntry | `rawentry` | id, project_id, text, status |
| ExtractedEvent | `extractedevent` | id, project_id, type, amount, counterparty, status |
| EventCorrection | `eventcorrection` | id, event_id, field_name, old/new_value |
| Worker | `worker` | id, project_id, name, type, identity_key, phone, account, daily_rate |
| WorkLog | `worklog` | id, project_id, worker_id, task_name, unit, quantity, amount |
| Invoice | `invoice` | id, project_id, vendor_id, total_amount, status |
| Payment | `payment` | id, project_id, entity_id, amount, type, direction, due_date |
| WorkerState | `workerstate` | id, project_id, worker_id, role, total_days, financial_balance |
| HistoryEntry | `historyentry` | id, project_id, input_text, change_type, delta |
| PendingInterpretation | `pendinginterpretation` | id, project_id, raw_input, canonical_event_type, semantic_action, status |
| NaturalInputJob | `natural_input_jobs` | id, job_id, project_id, trace_id, status, result |
| ShadowInterpretationLog | `shadow_interpretation_log` | id, project_id, input_text, legacy_json, shadow_json, diff_json |
| FinancialMigrationLog | `financial_migration_log` | id, project_id, input_text, chosen_system, reason |
| TraceEvent | `trace_events` | id (UUID), trace_id, event_name, event_group, event_index, duration_ms |
| TraceEventCounter | `trace_event_counter` | trace_id (PK), counter |

## Background Worker (RQ)

- **Queue Name**: `llm_tasks`
- **Timeout**: 600 seconds (10 minutes)
- **Redis**: `redis://localhost:6379` (configurable via `REDIS_URL`)
- **Entry Point**: `app/scripts/start_worker.py`
- **Job Function**: `app/jobs/natural_input_job.py::process_natural_input_job()`
- **Flow**: API enqueues → RQ picks up → creates/updates NaturalInputJob → runs unified pipeline → writes results → sets DONE/FAILED status
- **Resilience**: Retry with exponential backoff for Redis connection; job recovery from RUNNING status on restart

## Feature Flags

| Env Variable | Values | Purpose |
|-------------|--------|---------|
| `YARA_FINANCIAL_MIGRATION_MODE` | OFF / SHADOW_ONLY / A_B_TEST / LLM_PRIMARY | Controls which engine writes financial data |
| `YARA_USE_EXECUTION_ENGINE` | true (default) / false | Controls legacy vs new execution engine |
