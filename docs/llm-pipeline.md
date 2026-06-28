# LLM Pipeline

## Overview

The Yara LLM pipeline processes Persian natural language construction notes through a **dual-path architecture**: a deterministic semantic rules engine (legacy) runs in parallel with an LLM v2 interpreter (shadow). A governance engine decides which result to use for financial operations.

```
User Input (Persian Text)
    │
    ▼
┌────────────────────────────────────────────┐
│         INPUT SPLITTER                     │
│  _split_multi_event_text()                 │
│  → Splits by sentence boundaries           │
│  → Detects multi-event inputs              │
│  → Returns text chunks                     │
└────────┬───────────────────────┬───────────┘
         │                       │
         ▼                       ▼
┌────────────────┐    ┌──────────────────────┐
│ LEGACY PATH    │    │ SHADOW PATH (LLM v2) │
│ (deterministic)│    │ (AI-based)           │
│                │    │                      │
│ semantic_rule  │    │ LLMv2Interpreter     │
│ _engine.py     │    │ → Ollama API call    │
│ ~60 Persian    │    │ → System prompt      │
│ keyword rules  │    │ → temperature=0      │
│                │    │ → Structured JSON    │
│ CanonicalEvent │    │ → Pydantic validated │
│ with type,     │    │                      │
│ entity, amount │    │ StructuredEvent with │
│ direction      │    │ entities, amounts,   │
│                │    │ directions           │
└────────┬───────┘    └──────────┬───────────┘
         │                       │
         ▼                       ▼
┌────────────────────────────────────────────┐
│         COMPARISON ENGINE                  │
│  compare_legacy_vs_shadow.py               │
│  → Field-by-field diff                     │
│  → intent_match, entity_match,             │
│    amount_match, direction_match           │
│  → Logged to ShadowInterpretationLog       │
└────────┬───────────────────────┬───────────┘
         │                       │
         ▼                       ▼
┌────────────────────────────────────────────┐
│         GOVERNANCE ENGINE                  │
│  FinancialMigrationGate.decide()           │
│  Safety checks:                            │
│  1. Legacy/shadow output match?            │
│  2. Financial decision ready?              │
│  3. Entity resolved?                       │
│  4. Financial output safe?                 │
│                                            │
│  Migration mode:                           │
│  OFF      → always LEGACY                  │
│  SHADOW   → run LLM, use LEGACY           │
│  A_B_TEST → 50/50 random                   │
│  LLM_PRIMARY → LLM if safe, else LEGACY   │
│                                            │
│  → Returns {chosen_system, final_result}   │
│  → Logged to FinancialMigrationLog         │
└────────┬───────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│         DOMAIN ROUTER                      │
│  DomainRouterService.route()               │
│  → Routes to SETUP/FINANCIAL/WORK/NOTE/    │
│    ENTITY_UPDATE/MIXED                     │
│  → Returns {domain, schema, ui_type}       │
└────────┬───────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│         EXECUTION ENGINE                   │
│  ExecutionEngine.execute_confirmed...()    │
│  → Writes Payments, WorkLogs, Invoices     │
│  → Updates WorkerStates, HistoryEntries    │
│  → No re-interpretation or LLM             │
└────────┬───────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│         PENDING INTERPRETATION             │
│  Creates PendingInterpretation records     │
│  → status = PENDING                        │
│  → Awaiting user confirmation in UI        │
└────────────────────────────────────────────┘
```

## Prompt Structure

The LLM v2 system prompt (`services/prompts/llm_v2_prompt.py`) is structured as:

```
[SYSTEM] You are a Persian construction project assistant.
Extract structured data from Persian construction notes.

Output format (JSON):
{
  "entities": [
    {
      "name": "entity name",
      "type": "PERSON|VENDOR|CLIENT",
      "role_guess": "role from context",
      "field_updates": { "phone": "...", "account_number": "..." }
    }
  ],
  "financial_transactions": [
    {
      "direction": "INCOMING|OUTGOING|DEBT|DEFERRED",
      "amount": number,
      "currency": "IRR|IRR_MILLION|IRR_BILLION",
      "method": "CASH|BANK_TRANSFER|CHECK",
      "description": "..."
    }
  ],
  "work_entries": [
    {
      "task_name": "...",
      "quantity": number,
      "unit": "day|meter|item|project"
    }
  ],
  "notes": ["..."],
  "domain": "SETUP|FINANCIAL|WORK|MIXED"
}
```

Key prompt characteristics:
- **Persian + English mixed**: Instructions in English, expects Persian entity names
- **Temperature=0**: Deterministic output
- **JSON-only response**: Strict JSON parsing enforced
- **Context window**: Limited to single input (no conversation history)

## Interpreter Flow (`services/llm_v2_interpreter.py`)

```
Input: Persian text string
    │
    ▼
1. Build system prompt with structured JSON schema
    │
    ▼
2. Call Ollama API:
   - POST to OLLAMA_BASE_URL/api/generate
   - Model: OLLAMA_MODEL (configurable)
   - Temperature: 0
   - Timeout: 60s
    │
    ▼
3. Parse JSON response into StructuredEvent Pydantic model
    │
    ▼
4. Validate via LLMv2Validator:
   - JSON parses correctly?
   - Entity names match known DB entities?
   - Financial amounts valid?
   - Direction consistent?
    │
    ▼
5. Success → return StructuredEvent
   Failure → retry (up to 2 retries)
   All retries failed → fallback to semantic rules
    │
    ▼
6. Emit observability events (LLM_STARTED, LLM_COMPLETED, LLM_FAILED)
   Record timing, token count, error rates
```

## Domain Routing Logic (`services/domain_router_service.py`)

The router classifies interpreted input into one of six domain types:

| Domain | Trigger | UI Schema |
|--------|---------|-----------|
| `SETUP` | Actions: ADD_ENTITY, UPDATE_ENTITY, SET_ROLE, SETUP | `SetupModal` |
| `FINANCIAL` | Actions: PAYMENT, PAYMENT_IN, PAYMENT_OUT, DEBT_CREATED, CHECK_PAYMENT | `FinancialModal` |
| `WORK` | Actions: WORK_LOG, TASK_ENTRY, DAILY_WORK, WORK_ENTRY | `WorkLogModal` |
| `ENTITY_UPDATE` | field_updates contains phone/account/daily_rate/notes | `EntityUpdateModal` |
| `MIXED` | Both SETUP + FINANCIAL entities present | `SplitFlowModal` |
| `NOTE` | Actions: NOTE, no financial/work/setup detected | Review card |

Routing priority: FINANCIAL > SETUP > WORK > NOTE

## Financial Guard Logic

The `FinancialMigrationGate` (`services/financial_migration_gate.py`) enforces a multi-layer safety system:

### Layer 1: Feature Flag
```
YARA_FINANCIAL_MIGRATION_MODE env var:
  OFF          → Legacy only (no LLM writes)
  SHADOW_ONLY  → Run LLM but discard results
  A_B_TEST     → Random 50/50 selection
  LLM_PRIMARY  → LLM with safety overrides
```

### Layer 2: Safety Checks
```
1. financial_outputs_match(diff)
   → Legacy and LLM agree on amount, direction, entity?

2. financial_decision_ready(governance)
   → Governance engine has approved financial migration?

3. legacy_has_resolved_entity(legacy_result)
   → Legacy system found a clear entity match?

4. shadow_financial_unsafe_reason(shadow_result)
   → LLM output contains unsafe patterns?
     (e.g., conflicting direction, missing entity,
      implausible amounts)
```

### Layer 3: Decision & Audit
```python
# Valid path examples:
OFF:          {"chosen": "LEGACY",  "reason": "Financial migration is OFF"}
SHADOW_ONLY:  {"chosen": "LEGACY",  "reason": "Shadow-only mode executes legacy"}
A_B_TEST:     {"chosen": "SHADOW",  "reason": "A/B test selected shadow"}
LLM_PRIMARY:  {"chosen": "SHADOW",  "reason": "LLM primary conditions passed"}

# All decisions logged to FinancialMigrationLog table
```

## Correction / Void System

### Correction Flow
```
User edits a confirmed record → PATCH endpoint
    │
    ▼
1. Validate new values against business rules
2. Update record fields
3. Set correction_note and corrected_at
4. Create HistoryEntry with change_type = correction
5. Recompute affected WorkerState balances
```

### Void Flow
```
User voids a record → POST /void endpoint
    │
    ▼
1. Set is_voided = true
2. Set void_reason (user-provided)
3. Set voided_at = now()
4. Create HistoryEntry with change_type = void
5. Reverse financial impact in WorkerState
```

### Voidable Record Types
- Payment (via `POST /projects/{id}/payments/{id}/void`)
- WorkLog (via `POST /projects/{id}/work-logs/{id}/void`)
- Payable/Invoice (via `POST /projects/{id}/payables/{id}/void`)
- Note/HistoryEntry (via `POST /projects/{id}/notes/{id}/void`)

All voidable records support:
- `is_voided: bool`
- `void_reason: str | None`
- `voided_at: datetime | None`

## Confidence Handling

- **Semantic rules**: No confidence score (binary match/no-match)
- **LLM v2**: Confidence tracked via `ai_confidence: float` on `ExtractedEvent`
- **PendingInterpretation**: `confidence: float | None` field
- **Governance decisions**: Logged with reason text explaining the choice
- **Performance logging**: All LLM calls have timing, token count, and error rate tracking via `performance_logger.py`
