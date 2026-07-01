# Execution Truth Model

> Production-grade specification of Yara's exact runtime behavior.
> Source of truth for debugging production issues.

---

## Section 1 — Event to Database Mapping

Every domain event maps to a precise set of database writes. No event writes to tables outside its domain mapping.

### 1.1 FINANCIAL Event

**Input example**: "وحید ۵۰۰ میلیون ریخت به حساب"

**Semantic actions**: `PAYMENT`, `PAYMENT_IN`, `PAYMENT_OUT`, `PAYMENT_RECEIVED`, `PURCHASE_PAID`, `PURCHASE_UNPAID`, `DEBT_CREATED`, `CHECK_PAYMENT`, `DEFERRED_PAYMENT`, `INVOICE`

#### Execution Engine Writes (`execution_engine.py:execution_engine._execute_impl`)

| Action | Table | Fields Written | Condition |
|--------|-------|---------------|-----------|
| `PAYMENT` | `payment` | `project_id`, `entity_id`, `amount`, `type` (default `BANK_TRANSFER`), `direction`, `due_date`, `description`, `related_invoice_id` | direction must be non-null |
| `PAYMENT` | `worker_state` | `financial_balance ±= amount`, `role` = `CLIENT` if INCOMING else decrement if not CLIENT/VENDOR | state exists or auto-created |
| `PURCHASE_PAID` | `payment` | same as PAYMENT, but `type` = `CASH`, `direction` = `OUTGOING` | — |
| `DEBT_CREATED` / `INVOICE` | `invoice` | `project_id`, `vendor_id`, `total_amount`, `description`, `status` = `OPEN` | — |
| `DEBT_CREATED` / `INVOICE` | `worker_state` | `role` = `VENDOR`, `financial_balance += amount` | state exists or auto-created |
| `CHECK_PAYMENT` / `DEFERRED_PAYMENT` | `payment` | same as PAYMENT, but `type` = `CHECK`, `direction` = `DEFERRED` (default) | — |

#### Route Handler Writes (`projects.py` confirming a PendingInterpretation)

| Table | Fields Written | Condition |
|-------|---------------|-----------|
| `pendinginterpretation` | `status` = `CONFIRMED` | always on confirm |
| `historyentry` | `project_id`, `input_text`, `change_type` = `PAYMENT`/`INVOICE`, `delta` = `{amount, balance}`, `worker_state_id` | always |
| `worker_state` | `financial_balance`, `total_days_worked`, `total_quantity` | updated via engine |
| `payment` | see above | via ExecutionEngine |
| `invoice` | see above | via ExecutionEngine |

#### RawEntry Writes (pipeline start)

| Table | Fields Written |
|-------|---------------|
| `rawentry` | `project_id`, `text`, `status` = `PENDING` → `PROCESSED` |

#### Direction → WorkerStateRole Mapping

| `financial_direction` | `worker_state.role` |
|-----------------------|---------------------|
| `INCOMING` | `CLIENT` |
| `OUTGOING` | `VENDOR` (or decrement non-VENDOR/CLIENT balance) |
| `DEBT` | `VENDOR` |
| `DEFERRED` | `VENDOR` |

---

### 1.2 SETUP Event

**Input example**: "کارفرمای پروژه میثم کبیری است"

**Semantic actions**: `ADD_ENTITY`, `UPDATE_ENTITY`, `SET_ROLE`, `SETUP`

#### Writes

| Table | Fields Written | Condition |
|-------|---------------|-----------|
| `worker` | `project_id`, `name`, `type` (from role), `identity_key`, `role_detail`, `phone`, `account_number`, `daily_rate`, `notes` | new entity |
| `worker_state` | `project_id`, `worker_id`, `name`, `role` | auto-created if not exists |
| `pendinginterpretation` | `status` = `CONFIRMED` | on confirm |
| `historyentry` | `input_text`, `change_type` = `SETUP`, `worker_state_id` | always |

#### Worker Type Mapping

| Persian Role Phrase | `worker.type` | `worker_state.role` |
|--------------------|---------------|---------------------|
| "کارفرما" | `CLIENT` | `CLIENT` |
| "کارگر روزمزد" / "کارگر ساده" | `DAILY_WORKER` | `DAILY` |
| "جوشکار" / "استادکار" / "نیروی متخصص" | `SKILLED_WORKER` | `SKILLED` |
| "فروشنده" / "تامین‌کننده" | `VENDOR` | `VENDOR` |
| "پیمانکار" / other | `OTHER` | `DAILY` |

#### Identity Key

Generated in `identity_key.py`:
```
identity_key = normalize_name(name) + "|" + phone_digits
```
Unique per project (enforced by `ix_worker_project_identity_key`).

---

### 1.3 WORK Event

**Input example**: "مش رحیم امروز کار کرد"

**Semantic actions**: `WORK_LOG`, `TASK_ENTRY`, `DAILY_WORK`, `WORK_ENTRY`

#### Writes

| Table | Fields Written | Condition |
|-------|---------------|-----------|
| `worklog` | `project_id`, `worker_id`, `task_name`, `unit`, `quantity`, `rate_per_unit`, `total_amount`, `period_label`, `description` | always |
| `worker_state` | `total_days_worked += quantity`, `total_quantity += quantity`, `unit` | state exists or auto-created |
| `pendinginterpretation` | `status` = `CONFIRMED` | on confirm |
| `historyentry` | `input_text`, `change_type` = `WORK`, `worker_state_id` | always |

#### Work Unit Default

| Detected Pattern | `worklog.unit` |
|-----------------|----------------|
| "کار کرد" / روزمزد | `day` |
| "جوشکاری" / "meter" pattern | `meter` |
|数量的 explicit unit | as detected |
| fallback | `day` |

---

### 1.4 ENTITY_UPDATE Event

**Input example**: "شماره تماس وحید ۰۹۱۲۱۲۳۴۵۶۷"

**Semantic actions**: `PHONE_UPDATE`, `ACCOUNT_UPDATE`, `DAILY_RATE_UPDATE`, `NOTES_UPDATE`, `GENERAL_PROFILE_UPDATE`

#### Field Update Keys

```python
_PROFILE_FIELD_KEYS = {
    "phone", "account_number", "accountNumber",
    "card_number", "cardNumber",
    "daily_rate", "dailyRate",
    "notes"
}
```

#### Writes

| Table | Fields Written | Condition |
|-------|---------------|-----------|
| `worker` | `phone`, `account_number`, `daily_rate`, `notes` (specific fields only) | entity must be resolved |
| `pendinginterpretation` | `status` = `CONFIRMED` | on confirm |
| `historyentry` | `input_text`, `change_type` = `ENTITY_UPDATE`, `delta` = `{field_updates}` | always |

---

### 1.5 NOTE Event

**Input example**: "یادداشت: مصالح فردا میرسه"

**Semantic actions**: `NOTE` (catch-all when no other domain matches)

#### Writes

| Table | Fields Written | Condition |
|-------|---------------|-----------|
| `historyentry` | `project_id`, `input_text`, `change_type` = `NOTE` | always |
| `pendinginterpretation` | `status` = `CONFIRMED` | on confirm |

No financial or work tables are touched.

---

### 1.6 Correction / Void Writes

#### Correction (`PATCH /projects/{id}/payments/{id}`, `PATCH /projects/{id}/work-logs/{id}`, etc.)

| Table | Fields Written |
|-------|---------------|
| Target record | Updated fields from payload + `corrected_at = now()` + `correction_note` |
| `historyentry` | `change_type` = correction type |

#### Void (`POST /projects/{id}/payments/{id}/void`, etc.)

| Table | Fields Written |
|-------|---------------|
| Target record | `is_voided = true`, `void_reason = payload.reason`, `voided_at = now()` |
| `historyentry` | `change_type` = void type |

---

## Section 2 — State Machine

### 2.1 NaturalInputJob Lifecycle

```
                    ┌──────────┐
                    │ PENDING  │
                    └────┬─────┘
                         │ RQ worker picks up job
                         ▼
                    ┌──────────┐
            ┌───────│ RUNNING  │────────┐
            │       └──────────┘        │
            │  pipeline succeeds        │ pipeline raises
            ▼                           ▼
      ┌──────────┐               ┌──────────┐
      │   DONE   │               │  FAILED  │
      └──────────┘               └──────────┘
```

#### State Transitions

| From | To | Trigger | Who | DB Change |
|------|----|---------|-----|-----------|
| `PENDING` | `RUNNING` | RQ worker starts `process_natural_input_job()` | Worker | `job.status = RUNNING`, `job.error = None` |
| `RUNNING` | `DONE` | Pipeline completes without exception | Worker | `job.status = DONE`, `job.result = {interpretations: [...]}` |
| `RUNNING` | `FAILED` | Any exception during pipeline | Worker | `job.status = FAILED`, `job.error = str(e)` |
| `PENDING` | `FAILED` | Worker crashes before setting RUNNING | Worker (finally) | `job.status = FAILED`, `job.error = "job exited before reaching a terminal state"` |
| `RUNNING` | `FAILED` | Worker crashes mid-execution | Worker (finally) | `job.status = FAILED` on recovery |

**Guarantee**: The `finally` block in `process_natural_input_job()` ensures any job not in `{DONE, FAILED}` is force-failed.

### 2.2 RawEntry Lifecycle

```
┌──────────┐     ┌───────────┐     ┌──────────┐
│ PENDING  │────▶│ PROCESSED │────▶│  (done)  │
└──────────┘     └───────────┘     └──────────┘
     │
     ▼
┌──────────┐
│  FAILED  │
└──────────┘
```

| Transition | Trigger | Where |
|------------|---------|-------|
| `PENDING` → `PROCESSED` | After successful pipeline execution | `natural_input_job.py` worker |
| `PENDING` → `FAILED` | Pipeline raises exception before completion | `natural_input_job.py` worker |

### 2.3 PendingInterpretation Lifecycle

```
                    ┌───────────┐
                    │  PENDING  │
                    └─────┬─────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌──────────┐┌──────────┐┌──────────┐
        │CONFIRMED ││  EDITED  ││DISCARDED │
        └──────────┘└──────────┘└──────────┘
              │
              ▼
          (finalized)
```

| From | To | Trigger | Who |
|------|----|---------|-----|
| `PENDING` | `CONFIRMED` | User confirms via UI | API (`confirm_pending_interpretation`) |
| `PENDING` | `EDITED` | User edits fields via UI | API (`update_pending_interpretation`) |
| `EDITED` | `CONFIRMED` | User confirms after edit | API (`confirm_pending_interpretation`) |
| `PENDING` | `DISCARDED` | User discards | API (`discard_pending_interpretation`) |
| `EDITED` | `DISCARDED` | User discards after edit | API (`discard_pending_interpretation`) |

**Rejection**: If status is `CONFIRMED` or `DISCARDED`, any confirm/discard request returns `409 CONFLICT`.

### 2.4 Record Void Lifecycle

```
┌──────────┐     ┌──────────┐
│  ACTIVE  │────▶│  VOIDED  │
└──────────┘     └──────────┘
  is_voided=false   is_voided=true
                    voided_at=now()
                    void_reason="..."
```

Applies to: `Payment`, `WorkLog`, `Invoice`, `HistoryEntry`.

**Guarantee**: Voided records are never modified again. Any PATCH on a voided record returns `400` via `_ensure_not_voided()`.

---

## Section 3 — Failure Model

### 3.1 LLM Fails (timeout / invalid JSON / Ollama down)

```
Event: LLMv2Interpreter.interpret() raises or returns invalid JSON
    │
    ├── Retry logic: up to 2 retries with same input
    │
    ├── All retries exhausted => llm_v2_result["_llm_v2_failed"] = True
    │
    ├── Pipeline behavior:
    │   ├── If LLM valid: use LLM output as primary (skip legacy entirely)
    │   ├── If LLM invalid + valid semantic result: use legacy + governance
    │   └── If LLM invalid + no semantic result: fallback to safe_note
    │
    ├── Fallback path (unified_pipeline.py:317-446):
    │   1. Try fast paths (work_log, safe_note, setup, profile_update)
    │   2. Try profile_update interpretation
    │   3. Try safe_note interpretation
    │   4. Run full legacy semantic engine
    │
    ├── User-visible:
    │   ├── Job completes with DONE status (unless ALL paths fail)
    │   ├── PendingInterpretation[] returned (from legacy/fallback)
    │   └── AiProcessingStatus shows success (but may have used fallback path)
    │
    └── Logged:
        ├── Trace event: LLM_FAILED with error_message
        ├── Pipeline performance: fallback_required=True
        └── Request cache: llm_results contains _llm_v2_failed dict
```

### 3.2 Redis Queue Fails

```
Event: get_queue() fails or RQ.enqueue() fails
    │
    ├── API behavior:
    │   ├── Natural input request returns HTTP 500
    │   ├── No RawEntry is created (transaction rolled back)
    │   └── No job is enqueued
    │
    ├── Redis connection retry:
    │   ├── get_redis_connection() retries with exponential backoff
    │   ├── 0.5s → 1s → 2s → 4s → ... → max 30s
    │   └── Each connection attempt has 5s socket timeout
    │
    ├── User-visible:
    │   └── "خطایی رخ داد. دوباره تلاش کنید." error toast
    │
    └── Logged:
        └── "Redis unavailable (attempt N): ..." warning log
```

### 3.3 DB Transaction Fails Mid-Execution

```
Event: Any db.commit() fails (constraint violation, deadlock, connection loss)
    │
    ├── In pipeline (natural_input_job.py):
    │   ├── try: executes pipeline, db.commit()
    │   ├── except: db.rollback(), sets job.status = FAILED
    │   └── finally: additional rollback + force-fail if not terminal
    │
    ├── In API handlers:
    │   ├── FastAPI's default exception handler returns 500
    │   ├── Session is rolled back by dependency lifecycle
    │   └── No partial writes visible to subsequent requests
    │
    ├── In ExecutionEngine:
    │   ├── Raises ValueError or propagates DB exception
    │   ├── Tracked as ERROR_OCCURRED trace event
    │   └── Caller (confirm handler) sees exception and halts
    │
    ├── Guarantee:
    │   ├── All writes within a single request are atomic
    │   ├── No partial state: Payment without HistoryEntry cannot occur
    │   └── WorkerState.financial_balance always consistent with payments
    │
    └── Logged:
        ├── Trace event: DB_WRITE_FAILURE or ERROR_OCCURRED
        └── "execution_engine_failed" log with duration_ms
```

### 3.4 Partial Execution Occurs

```
Event: Pipeline writes RawEntry + PendingInterpretation but subsequent step fails
    │
    ├── Atomicity boundary:
    │   ├── RawEntry + PendingInterpretation write in one commit
    │   └── If commit succeeds, both are visible; if fails, neither is
    │
    ├── NaturalInputJob status:
    │   └── FAILED with error message, result may contain partial events
    │
    ├── Recovery:
    │   ├── User sees FAILED status, can retry
    │   └── Retry creates new job_id, new RawEntry, new PendingInterpretations
    │
    └── Cleanup:
        └── Old FAILED entries remain in DB for audit (no automatic cleanup)
```

### 3.5 Entity Cannot Be Resolved

```
Event: LLM or legacy extracts entity name but no matching Worker found
    │
    ├── PendingInterpretation created with:
    │   ├── suggested_entity_id = None
    │   ├── extracted_entities = [{name: "...", type: "...", requires_confirmation: true}]
    │   └── confidence = <value> (may be low)
    │
    ├── User-visible:
    │   ├── DomainUIController shows EntityUpdateModal or SetupModal
    │   ├── Candidate list presented if similar names exist
    │   └── User can:
    │       ├── Select existing worker from candidates
    │       ├── Create new worker with provided name/role
    │       └── Edit extracted data before confirming
    │
    ├── API confirm behavior:
    │   ├── If payload has entity_id: use existing worker
    │   ├── If payload has create_new: create Worker + WorkerState
    │   ├── If payload ambiguous: return NEEDS_SELECTION error
    │   └── On success: set suggested_entity_id, proceed to execution
    │
    └── Logged:
        └── Trace event: ENTITY_RESOLUTION_REQUIRED
```

### 3.6 Financial Amount Cannot Be Parsed

```
Event: persian_money_engine.parse_persian_money() returns 0 or None
    │
    ├── In legacy path:
    │   ├── extracted_amount = None on PendingInterpretation
    │   ├── Domain routes as NOTE or SETUP instead of FINANCIAL
    │   └── No financial execution occurs
    │
    ├── In LLM path:
    │   ├── LLM may still extract an amount from context
    │   ├── If LLM amount valid, governance may still route FINANCIAL
    │   └── FinancialMigrationGate validates amount via decimal_or_none()
    │
    ├── At confirmation:
    │   ├── ExecutionEngine raises ValueError("Amount missing in confirmed interpretation")
    │   ├── User sees error, must edit and provide amount
    │   └── Fatal: confirmation fails until amount is provided
    │
    └── User-visible:
        └── FinancialModal shows amount field as editable, user must fill
```

---

## Section 4 — Decision Logic (Legacy vs LLM)

### 4.1 Decision Tree

```
For every natural input that is NOT a fast-path match:

INPUT enters unified_pipeline.process_input()
    │
    ├──> Fast Path Attempts (skips LLM + legacy entirely):
    │     ├── Daily work log? → create PendingInterpretation, return
    │     ├── Safe note? → create PendingInterpretation, return
    │     ├── Role assignment? → create PendingInterpretation, return
    │     ├── Profile update? → create PendingInterpretation, return
    │     └── Financial payment? → create PendingInterpretation, return
    │
    ├──> LLM v2 Path (always attempted if fast paths miss):
    │     ├── IF LLM succeeds AND validates:
    │     │   └── USE LLM output as primary, skip legacy entirely
    │     └── IF LLM fails OR invalid:
    │         └── FALLBACK to Legacy Path
    │
    ├──> Legacy Path (only when LLM fails or is skipped):
    │     ├── Semantic rule engine processes input
    │     ├── IF canonical_event_type == FINANCIAL AND shadow_result exists:
    │     │   └── RUN Governance Engine:
    │     │       └── DECISION LOGIC:
    │     │           ├── IF mode == OFF:
    │     │           │   └── Use LEGACY
    │     │           ├── IF mode == SHADOW_ONLY:
    │     │           │   └── Use LEGACY (LLM ran for data collection only)
    │     │           ├── IF mode == A_B_TEST:
    │     │           │   ├── IF random() < 0.5: Use LEGACY
    │     │           │   └── ELSE: Use SHADOW (LLM)
    │     │           ├── IF mode == LLM_PRIMARY:
    │     │           │   ├── IF ALL safety checks pass: Use SHADOW (LLM)
    │     │           │   └── ELSE: Use LEGACY
    │     │           └── DEFAULT: Use LEGACY
    │     └── ELSE (not FINANCIAL or no shadow):
    │         └── Use LEGACY (no governance needed)
```

### 4.2 WHEN LEGACY WINS

| Condition | Check | Source |
|-----------|-------|--------|
| Financial inconsistency detected | `financial_outputs_match(diff)` returns `False` | `financial_validator.py:5` |
| Missing entity resolution | `legacy_has_resolved_entity()` returns `False` | `financial_validator.py:42` |
| Low LLM confidence | `shadow_result.confidence < 0.85` | `financial_validator.py:26` |
| LLM ambiguity flagged | `shadow_result.ambiguity == True` | `financial_validator.py:28` |
| Governance rejection | `financial_decision_ready()` returns `False` | `financial_validator.py:12` |
| LLM output unsafe | `shadow_financial_unsafe_reason()` returns non-None | `financial_validator.py:24` |
| LLM failed entirely | `llm_v2_result._llm_v2_failed == True` | `unified_pipeline.py:267` |
| Migration mode OFF | `feature_flags.get_financial_migration_mode() == OFF` | `feature_flags.py` |
| Migration mode SHADOW_ONLY | mode == SHADOW_ONLY | `financial_migration_gate.py:50` |

### 4.3 WHEN LLM WINS

| Condition | Check | Source |
|-----------|-------|--------|
| LLM v2 validates successfully | `LLMv2Validator.validate()` passes | `unified_pipeline.py:268-277` |
| All fields match legacy | `financial_outputs_match(diff)` returns `True` | `financial_validator.py:5` |
| Confidence >= 0.85 | `shadow_result.confidence >= 0.85` | `financial_validator.py:26` |
| No ambiguity | `shadow_result.ambiguity != True` | `financial_validator.py:28` |
| Entity resolved | `legacy_has_resolved_entity()` returns `True` | `financial_validator.py:42` |
| Governance approves | `financial_decision_ready()` returns `True` | `financial_validator.py:12` |
| A/B test selects shadow | `random.random() < 0.5` | `financial_migration_gate.py:57` |
| LLM_PRIMARY + all checks pass | mode == LLM_PRIMARY + all safety checks | `financial_migration_gate.py:61-73` |

### 4.4 WHEN FALLBACK OCCURS

| Scenario | Fallback Behavior | User Visible |
|----------|------------------|--------------|
| LLM timeout (60s) | Retry twice, then skip to legacy | Job completes via legacy path |
| LLM invalid JSON | Retry twice, then skip to legacy | Job completes via legacy path |
| LLM returns empty entities | LLM validates but no entities → skip to legacy | Job completes via legacy path |
| Fast path matches | No LLM, no legacy | Instant response (no AI spinner delay) |
| All paths fail | `safe_note` interpretation as last resort | PendingInterpretation with NOTE type |
| Critical exception in pipeline | Job status = FAILED | "پردازش با خطا مواجه شد" error in UI |

### 4.5 Governance Decision Logging

Every governance decision is logged to `financial_migration_log`:
```
chosen_system = "LEGACY" | "SHADOW"
reason = human-readable explanation string
legacy_json = full legacy result
shadow_json = full LLM result
```

Additionally, shadow-vs-legacy comparisons are logged to `shadow_interpretation_log`:
```
diff_json = {intent_match, entity_match, amount_match, direction_match}
```

---

## Section 5 — Execution Engine Behavior

### 5.1 Core Contract

`ExecutionEngine` in `services/execution_engine.py` is the **single source of truth** for all confirmed financial/event writes.

```python
@dataclass(frozen=True)
class ConfirmedFinancialInterpretation:
    project_id: int
    semantic_action: str        # PAYMENT, PURCHASE_PAID, DEBT_CREATED, etc.
    amount: Decimal | int | str | None
    entity_id: int | None
    financial_direction: FinancialDirection | str | None
    payment_method: PaymentType | str | None
    due_date: str | None
    description: str | None
    related_invoice_id: int | None
```

**Rules:**
1. NEVER re-interprets text
2. NEVER uses LLM
3. NEVER uses semantic rules
4. NEVER creates PendingInterpretation
5. ONLY writes to: `payment`, `invoice`, `worker_state`
6. ALWAYS validates amount is non-null
7. ALWAYS validates entity_id resolves to a real Worker in the project
8. ALWAYS auto-creates WorkerState if missing

### 5.2 What It Writes

| Action | Writes To | Side Effects |
|--------|-----------|--------------|
| `PAYMENT` | `payment` + `worker_state.financial_balance` | Balance += amount if INCOMING (CLIENT), balance -= amount if OUTGOING |
| `PURCHASE_PAID` | `payment` (cash, outgoing) + `worker_state` | Balance -= amount |
| `DEBT_CREATED` / `INVOICE` | `invoice` + `worker_state` | Balance += amount, role = VENDOR |
| `CHECK_PAYMENT` / `DEFERRED_PAYMENT` | `payment` (check, deferred) + `worker_state` | Balance -= amount |

### 5.3 What It NEVER Writes

- `worker` table (entity profile) — handled by `entity_registry.py`
- `worklog` table — handled by legacy route handlers
- `historyentry` table — handled by route handlers after engine returns
- `pendinginterpretation` — created before engine runs
- `natural_input_jobs` — managed by job orchestrator

### 5.4 Idempotency

The engine does **not** enforce natural-input idempotency keys. Those keys are enforced before the engine runs.

Natural input submission is idempotent at `POST /projects/{project_id}/natural-input`:

- The request accepts `idempotency_key`.
- `rawentry` stores the key with `project_id`.
- The database enforces `UNIQUE(project_id, idempotency_key)`.
- A duplicate `(project_id, idempotency_key)` returns the existing `NaturalInputJob` response and does not create another `RawEntry` or enqueue another RQ job.

Worker retry handling is idempotent for already-known jobs:

- If `process_natural_input_job()` sees the job is already `DONE` or `FAILED`, it returns the stored job result/error and does not run extraction again.
- A pending job is claimed with an atomic `UPDATE ... WHERE status = PENDING` before the pipeline runs. A parallel worker that loses that claim returns the current job state and does not process the input.
- If an RQ retry sees a job that was already `RUNNING`, it first reuses existing pending interpretations for the same project and input text instead of creating another set.
- `RawEntry.status` moves to `PROCESSED` only after a successful job and to `FAILED` only when the job fails.

Duplicate confirmations of the same PendingInterpretation are prevented by the confirmation transaction:

- The confirmation endpoint locks the `pendinginterpretation` row with `SELECT FOR UPDATE`.
- The row is claimed as `CONFIRMING` inside the transaction and only becomes `CONFIRMED` at the final commit.
- `payment.source_pending_interpretation_id` and `invoice.source_pending_interpretation_id` have unique constraints. If a database or test environment does not enforce row locks, the second financial insert still fails and returns `409`.
- `ExecutionEngine` locks the target `workerstate` row with `SELECT FOR UPDATE` before balance math.
- DB-backed observability events are not written from inside the uncommitted financial transaction; this prevents logging from committing partial financial state.

#### Guarantees

- The same natural input submission retried with the same key creates at most one `RawEntry` and one `NaturalInputJob`.
- Fast client retries and duplicate HTTP submissions with the same key do not enqueue duplicate jobs.
- Retrying a terminal worker job does not recreate `PendingInterpretation`, `Payment`, `Invoice`, `WorkLog`, or `HistoryEntry` rows.
- Reconfirming an already closed interpretation returns `409` before financial writes, so balances and financial records change at most once per interpretation.
- Payment/invoice writes created from confirmation are tied to the source `PendingInterpretation`, and the database rejects duplicate source writes.
- Payment/invoice/worker_state/history writes for confirmation commit together. If history creation or any later step fails, the transaction rolls back and the transient `CONFIRMING` claim is restored to an open state.

#### Not Yet Guaranteed

- The retry reuse path for a recovered `RUNNING` job matches by project and raw input text because `PendingInterpretation` does not yet store `job_id` or `raw_entry_id`. This prevents the known retry duplicate path, but a future schema link from `PendingInterpretation` to `NaturalInputJob` would make the guarantee stricter and easier to audit.

### 5.5 Reconciliation and Safety Monitoring

Reconciliation is a read-only safety layer by default. It recomputes financial truth from source records and stores a review snapshot; it never silently overwrites balances, payments, invoices, work logs, or history.

`financial_reconciliation_service.py` computes:

- `expected_worker_balance` from non-voided payments, invoices, and financially relevant work logs.
- `expected_project_balance` from incoming payments minus real outgoing payments.
- `expected_payables` from open vendor invoices plus unpaid worker balances.
- drift snapshots comparing recomputed values to `worker_state.financial_balance` and project-level totals.

When drift is detected:

- `project.reconciliation_status` becomes `DRIFT_DETECTED`.
- a `reconciliation_event` row is written with status `NEEDS_REVIEW`.
- the snapshot stores stored values, recomputed values, and differences for audit.
- no automatic financial correction is applied in the MVP.

Safety recovery:

- failed natural-input jobs are copied to `dead_letter_job` with job id, payload, error trace, retry count, source, and timestamp.
- `GET /admin/dlq-jobs` exposes failed jobs so worker failures are not silent.
- `recover_stuck_confirming_interpretations()` finds stale `CONFIRMING` rows. If committed financial records exist, it marks them `CONFIRMED`; otherwise it rolls them back to `PENDING`.
- `GET /admin/reconciliation-report/{project_id}` returns stored balances, recomputed balances, drift differences, and the last reconciliation timestamp.
- `GET /admin/safety-metrics` reports processed financial events, drift events, DLQ count, current stuck `CONFIRMING` count, and duplicate-prevention count.

**Guarantee**: The system is eventually consistent via reconciliation and review. Reconciliation detects silent drift and records evidence, but destructive correction remains an explicit future admin action.

### 5.6 Consistency Guarantees

```
Within a single db.commit() after ExecutionEngine runs:
  ├── payment(s) created (if FINANCIAL)
  ├── invoice(s) created (if DEBT/INVOICE)
  ├── worker_state updated (balance always consistent)
  ├── history_entry created (with delta = {amount, balance})
  └── pendinginterpretation.status = CONFIRMED

All or nothing: any failure before commit rolls back everything.
```

### 5.7 Amount Handling

```python
def _amount(self, value: Decimal | int | str | None) -> Decimal | None:
    if value is None:
        return None       # Will raise ValueError("Amount missing") later
    return Decimal(str(value))

def _direction(self, value: FinancialDirection | str | None) -> FinancialDirection | None:
    if value is None:
        return None
    if isinstance(value, FinancialDirection):
        return value
    return FinancialDirection(value)  # May raise ValueError for invalid strings
```

---

## Section 6 — Real-World Examples

### Example 1: Simple Incoming Payment

```
Input: "وحید ۵۰۰ میلیون ریخت به حساب"
Domain: FINANCIAL
Semantic Action: PAYMENT
Direction: INCOMING
Amount: 500,000,000 IRR
Entity: "وحید" → Worker (VENDOR or CLIENT)
```

**DB Changes:**

| Table | Change |
|-------|--------|
| `rawentry` | `{text: "وحید ۵۰۰ میلیون ریخت به حساب", status: PROCESSED}` |
| `pendinginterpretation` | `{canonical_event_type: FINANCIAL, semantic_action: PAYMENT, extracted_amount: 500000000, financial_direction: INCOMING, status: CONFIRMED}` |
| `payment` | `{entity_id: N, amount: 500000000, direction: INCOMING, type: BANK_TRANSFER}` |
| `worker_state` | `{role: CLIENT, financial_balance: +500000000}` |
| `historyentry` | `{change_type: PAYMENT, delta: {amount: 500000000, balance: 500000000}}` |

**UI Modal:** FinancialModal — shows entity "وحید", amount ۵۰۰,۰۰۰,۰۰۰, direction "دریافتی", method "انتقال بانکی"

---

### Example 2: Outgoing Payment

```
Input: "۱۰۰ میلیون دادم به جوشکار"
Domain: FINANCIAL
Semantic Action: PAYMENT
Direction: OUTGOING
Amount: 100,000,000 IRR
Entity: Resolved SKILLED_WORKER or unknown "جوشکار"
```

**DB Changes:**

| Table | Change |
|-------|--------|
| `rawentry` | `{text: "۱۰۰ میلیون دادم به جوشکار", status: PROCESSED}` |
| `pendinginterpretation` | `{canonical_event_type: FINANCIAL, semantic_action: PAYMENT, extracted_amount: 100000000, financial_direction: OUTGOING}` |
| `payment` | `{amount: 100000000, direction: OUTGOING, type: BANK_TRANSFER}` |
| `worker_state` | `{financial_balance: -100000000}` (if entity is not CLIENT or VENDOR) |
| `historyentry` | `{change_type: PAYMENT, delta: {amount: 100000000}}` |

**UI Modal:** FinancialModal — amount ۱۰۰,۰۰۰,۰۰۰, direction "پرداختی"

---

### Example 3: Setup Role Assignment

```
Input: "کارفرمای پروژه میثم کبیری است"
Domain: SETUP
Semantic Action: SETUP / ADD_ENTITY
Entity: "میثم کبیری" → CLIENT
```

**DB Changes:**

| Table | Change |
|-------|--------|
| `rawentry` | `{text: "کارفرمای پروژه میثم کبیری است", status: PROCESSED}` |
| `pendinginterpretation` | `{canonical_event_type: SETUP, semantic_action: ADD_ENTITY}` |
| On confirm: | |
| `worker` | `{name: "میثم کبیری", type: CLIENT, identity_key: "میثم کبیری\|"}` |
| `worker_state` | `{name: "میثم کبیری", role: CLIENT, financial_balance: 0}` |
| `historyentry` | `{change_type: SETUP, input_text: "..."}` |
| `pendinginterpretation` | `{status: CONFIRMED}` |

**UI Modal:** SetupModal — pre-filled name "میثم کبیری", role "کارفرما"

---

### Example 4: Work Log Entry

```
Input: "مش رحیم امروز کار کرد"
Domain: WORK
Semantic Action: WORK_LOG / DAILY_WORK
Entity: "مش رحیم" → DAILY_WORKER
Quantity: 1 (day)
```

**DB Changes:**

| Table | Change |
|-------|--------|
| `rawentry` | `{text: "مش رحیم امروز کار کرد", status: PROCESSED}` |
| `pendinginterpretation` | `{canonical_event_type: WORK, semantic_action: DAILY_WORK, extracted_quantity: 1}` |
| On confirm: | |
| `worklog` | `{worker_id: N, task_name: "کار روزمزد", unit: day, quantity: 1, total_amount: (rate or null)}` |
| `worker_state` | `{total_days_worked: +1, total_quantity: +1}` |
| `historyentry` | `{change_type: WORK}` |
| `pendinginterpretation` | `{status: CONFIRMED}` |

**Fast Path:** This input may match the daily work log fast path in `_build_daily_work_log_interpretation()`, which creates the PendingInterpretation immediately without calling LLM or legacy engine.

**UI Modal:** WorkLogModal — shows entity "مش رحیم", quantity ۱ روز

---

### Example 5: Ambiguous Sentence (Requires Confirmation)

```
Input: "نادری جوشکار ۵۰ میلیون"
Domain: FINANCIAL (or MIXED)
Ambiguity: "نادری" could be a SKILLED_WORKER or VENDOR
"۵۰ میلیون" could be payment received or paid
Direction: UNCLEAR
```

**Pipeline Behavior:**
1. Semantic rules detect financial keywords ("میلیون") + entity ("نادری")
2. LLM v2 may flag `ambiguity: true`
3. Governance engine checks: if ambiguity → LEGACY wins
4. If entity "نادری" has no matching Worker → `suggested_entity_id = None`

**DB Changes:**

| Table | Change |
|-------|--------|
| `rawentry` | `{text: "نادری جوشکار ۵۰ میلیون", status: PROCESSED}` |
| `pendinginterpretation` | `{canonical_event_type: FINANCIAL, extracted_amount: 50000000, suggested_entity_id: null, confidence: low}` |
| No execution writes until confirmed | |

**UI Modal:** EntityUpdateModal with candidate list + FinancialModal (amount pre-filled, direction requires user selection)

**User must:**
1. Resolve entity: select existing "نادری" or create new
2. Set direction: INCOMING or OUTGOING
3. Confirm → ExecutionEngine writes final records

**If user confirms without resolving entity:** API returns `409 CONFLICT` with `{status: "NEEDS_SELECTION", candidates: [...]}` → DomainUIController shows candidate selector.
