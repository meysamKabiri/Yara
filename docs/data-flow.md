# Data Flow

## End-to-End Flow: User Input → DB → UI

### Step-by-Step

```
1. USER INPUT (Frontend)
   ┌─────────────────────────────────────────────────────┐
   │ User types Persian text in ProjectDetailPage chat   │
   │ e.g. "۱۰۰ میلیون دادم به جوشکار"                     │
   │ → form submit → POST /projects/{id}/natural-input   │
   └─────────────────────┬───────────────────────────────┘
                         │
2. API ENDPOINT (Backend)
   ┌─────────────────────┴───────────────────────────────┐
   │ projects.py handler:                                 │
   │ 1. Creates RawEntry (status=PENDING)                 │
   │ 2. Creates NaturalInputJob (status=PENDING)          │
   │ 3. Enqueues RQ job → get_queue().enqueue(            │
   │      process_natural_input_job, args, job_id=...)    │
   │ 4. Returns {job_id, trace_id} immediately            │
   └─────────────────────┬───────────────────────────────┘
                         │
3. RQ QUEUE
   ┌─────────────────────┴───────────────────────────────┐
   │ Redis queue "llm_tasks":                              │
   │ - RQ worker picks up job (start_worker.py)           │
   │ - Sets NaturalInputJob status = RUNNING              │
   │ - Initializes trace context (trace_id, job_id)       │
   │ - Emits "job.started" / "JOB_STARTED" trace events   │
   └─────────────────────┬───────────────────────────────┘
                         │
4. UNIFIED PIPELINE (core/unified_pipeline.py)
   ┌─────────────────────┴───────────────────────────────┐
   │ process_input(db, project_id, text):                  │
   │                                                      │
   │ 4a. TEXT SPLITTING                                   │
   │   _split_multi_event_text()                          │
   │   → Splits input by sentence boundaries              │
   │   → Returns list of text chunks                      │
   │                                                      │
   │ 4b. LEGACY PATH (deterministic)                      │
   │   semantic_rule_engine.py:                            │
   │   → Persian keyword matching (60+ rules)              │
   │   → Extracts CanonicalEventType                      │
   │   → Extracts entities, amounts, directions           │
   │   → Returns CanonicalEvent[]                         │
   │                                                      │
   │ 4c. LLM v2 PATH (shadow/AI)                          │
   │   LLMv2Interpreter.interpret(text):                  │
   │   → Ollama API call (temperature=0)                  │
   │   → System prompt: structured JSON output            │
   │   → Returns StructuredEvent with entities            │
   │   → Validates via LLMv2Validator                     │
   │   → Falls back to legacy on failure                  │
   │                                                      │
   │ 4d. COMPARE LEGACY vs SHADOW                         │
   │   compare_legacy_vs_shadow():                        │
   │   → Field-by-field diff                              │
   │   → intent_match, entity_match,                      │
   │     amount_match, direction_match booleans            │
   │                                                      │
   │ 4e. GOVERNANCE                                       │
   │   FinancialMigrationGate.decide():                   │
   │   → Checks migration mode (OFF/SHADOW_ONLY/          │
   │     A_B_TEST/LLM_PRIMARY)                            │
   │   → Validates safety checks                          │
   │   → Returns chosen_system + final_result             │
   │   → Logs to FinancialMigrationLog                    │
   │                                                      │
   │ 4f. DOMAIN ROUTING                                   │
   │   DomainRouterService.route():                       │
   │   → Classifies domain: SETUP/FINANCIAL/WORK/         │
   │     NOTE/ENTITY_UPDATE/MIXED                         │
   │   → Returns domain + schema type                     │
   │                                                      │
   │ 4g. EXECUTION ENGINE                                 │
   │   ExecutionEngine.execute_confirmed_interpretation(): │
   │   → Single source of truth for writes                │
   │   → Creates/updates Payments, WorkLogs,              │
   │     Invoices, WorkerStates                           │
   │   → No re-interpretation, no LLM                     │
   │                                                      │
   │ 4h. PENDING INTERPRETATION CREATION                  │
   │   Creates PendingInterpretation records               │
   │   → status = PENDING (awaiting user confirmation)    │
   │   → Stores extracted_entities, amounts, etc.         │
   └─────────────────────┬───────────────────────────────┘
                         │
5. DB WRITE
   ┌─────────────────────┴───────────────────────────────┐
   │ NaturalInputJob:                                     │
   │ - status = DONE (or FAILED on error)                 │
   │ - result = {interpretations: [...]}                  │
   │ - Emits "JOB_COMPLETED" / "job.completed" events     │
   │ RawEntry: status = PROCESSED                         │
   │ PendingInterpretation[]: status = PENDING            │
   │ ShadowInterpretationLog / FinancialMigrationLog      │
   └─────────────────────┬───────────────────────────────┘
                         │
6. FRONTEND POLLING / WEBSOCKET
   ┌─────────────────────┴───────────────────────────────┐
   │ Polling: GET /natural-input-jobs/{id} every 1200ms  │
   │ WebSocket: ws://host/ws/jobs/{job_id}               │
   │   → Receives real-time JOB_STARTED, DOMAIN_ROUTER,  │
   │     LLM_STARTED, LLM_COMPLETED, JOB_COMPLETED       │
   │   → AiProcessingStatus shows animated progress      │
   │                                                      │
   │ When status = DONE:                                  │
   │ → Loads pending interpretations                     │
   │ → Closes AiProcessingStatus overlay                  │
   │ → Renders interpretation cards via DomainUIController│
   └─────────────────────┬───────────────────────────────┘
                         │
7. USER CONFIRMATION (UI)
   ┌─────────────────────┴───────────────────────────────┐
   │ DomainUIController routes to correct modal:          │
   │                                                      │
   │ SETUP  → SetupModal                                  │
   │   User fills name, role, phone, account              │
   │   → POST /pending-interpretations/{id}/confirm       │
   │                                                      │
   │ FINANCIAL → FinancialModal                           │
   │   User selects entity, amount, direction             │
   │   → POST /pending-interpretations/{id}/confirm       │
   │                                                      │
   │ ENTITY_UPDATE → EntityUpdateModal                    │
   │   User updates phone, account, rate, notes           │
   │   → POST /pending-interpretations/{id}/confirm       │
   │                                                      │
   │ MIXED → SplitFlowModal                               │
   │   Step 1: entity info → Step 2: financial tx        │
   │   → POST /pending-interpretations/{id}/confirm       │
   │                                                      │
   │ WORK → WorkLogModal                                  │
   │   User confirms work log entry                       │
   │   → POST /pending-interpretations/{id}/confirm       │
   └─────────────────────┬───────────────────────────────┘
                         │
8. EXECUTION ENGINE (confirmation)
   ┌─────────────────────┴───────────────────────────────┐
   │ API handler receives confirmation:                   │
   │ 1. Validates user edits                              │
   │ 2. Calls ExecutionEngine with confirmed data         │
   │ 3. ExecutionEngine writes final records:             │
   │    - Payment (for FINANCIAL)                         │
   │    - WorkLog (for WORK)                              │
   │    - Worker (for SETUP)                              │
   │    - Worker updates (for ENTITY_UPDATE)              │
   │ 4. PendingInterpretation status = CONFIRMED          │
   │ 5. HistoryEntry created                              │
   │ 6. WorkerState updated (balance, days, quantity)     │
   └─────────────────────┬───────────────────────────────┘
                         │
9. UI UPDATE
   ┌─────────────────────┴───────────────────────────────┐
   │ Frontend reloads project data:                       │
   │ → GET /projects/{id} (refreshed detail)              │
   │ → GET /projects/{id}/payments                        │
   │ → GET /projects/{id}/work-logs                       │
   │ → GET /projects/{id}/workers                         │
   │ → UI rerenders with updated data                     │
   │ → Tab updates reflect new information                │
   └─────────────────────────────────────────────────────┘
```

## Correction / Void Flow

```
User clicks "Correct" or "Void" on a record
    │
    ▼
CorrectionModal / VoidModal (frontend)
    │
    ▼
API: PATCH /projects/{id}/payments/{id} (correction)
     POST /projects/{id}/payments/{id}/void  (void)
    │
    ▼
Backend:
- For correction: Updates record fields + sets correction_note + corrected_at
- For void: Sets is_voided=true + void_reason + voided_at
- Creates HistoryEntry with change_type = CORRECTION / VOID
    │
    ▼
UI refreshes data → shows voided badge or updated values
```

## CSV Export Flow

```
User opens Reports tab → selects date range → clicks CSV export
    │
    ▼
Frontend generates export URL with query params:
  /projects/{id}/exports/{type}.csv?from_date=X&to_date=Y
    │
    ▼
Backend generates CSV in-memory (via StringIO)
  → Sets Content-Type: text/csv
  → Sets Content-Disposition: attachment; filename="..."
  → Returns Response(...)
    │
    ▼
Browser downloads file
```

## Financial Migration Data Flow

```
Every natural input processes TWO paths in parallel:
    │
    ├── Legacy Path (deterministic)
    │   → semantic_rule_engine.py
    │   → Always executes
    │
    └── Shadow Path (LLM v2)
        → LLMv2Interpreter
        → Runs as "shadow" (doesn't write by default)
    │
    ▼
Compare legacy vs shadow → log to ShadowInterpretationLog
    │
    ▼
FinancialMigrationGate.decide():
    ┌──────────────┬──────────────────────────────────────┐
    │ Mode         │ Behavior                             │
    ├──────────────┼──────────────────────────────────────┤
    │ OFF          │ Always use legacy                    │
    │ SHADOW_ONLY  │ Run LLM but always use legacy        │
    │ A_B_TEST     │ Random 50/50 legacy vs LLM           │
    │ LLM_PRIMARY  │ Use LLM if safety checks pass        │
    └──────────────┴──────────────────────────────────────┘
    │
    ▼
Log decision to FinancialMigrationLog
    │
    ▼
Execute chosen system's result via ExecutionEngine
```
