# Yara Phase 1 API Test Flow

Assumes the backend is running at `http://localhost:8000`.

Set a convenience variable:

```bash
BASE_URL="http://localhost:8000"
```

## 1. Create Project

```bash
curl -s -X POST "$BASE_URL/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Kitchen Remodel"
  }'
```

Expected shape:

```json
{
  "id": 1,
  "name": "Kitchen Remodel",
  "created_at": "2026-06-16T10:00:00",
  "updated_at": "2026-06-16T10:00:00"
}
```

Use the returned `id` as `PROJECT_ID`:

```bash
PROJECT_ID=1
```

## 2. List Projects

```bash
curl -s "$BASE_URL/projects"
```

Expected shape:

```json
[
  {
    "id": 1,
    "name": "Kitchen Remodel",
    "created_at": "2026-06-16T10:00:00",
    "updated_at": "2026-06-16T10:00:00"
  }
]
```

## 3. Create Raw Entry

```bash
curl -s -X POST "$BASE_URL/projects/$PROJECT_ID/raw-entries" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Client paid me 1200 for cabinets"
  }'
```

Expected shape:

```json
{
  "id": 1,
  "project_id": 1,
  "text": "Client paid me 1200 for cabinets",
  "status": "PENDING",
  "created_at": "2026-06-16T10:01:00",
  "updated_at": "2026-06-16T10:01:00"
}
```

Use the returned `id` as `RAW_ENTRY_ID`:

```bash
RAW_ENTRY_ID=1
```

## 4. Run Extraction

```bash
curl -s -X POST "$BASE_URL/projects/$PROJECT_ID/raw-entries/$RAW_ENTRY_ID/extract"
```

Expected shape:

```json
[
  {
    "id": 1,
    "project_id": 1,
    "raw_entry_id": 1,
    "type": "MONEY_IN",
    "counterparty_name": null,
    "counterparty_type": "UNKNOWN",
    "amount": "1200.00",
    "description": "Client paid me 1200 for cabinets",
    "event_date": null,
    "confidence": "0.5000",
    "status": "PENDING",
    "created_at": "2026-06-16T10:02:00",
    "updated_at": "2026-06-16T10:02:00"
  }
]
```

Use the returned event `id` as `EVENT_ID`:

```bash
EVENT_ID=1
```

## 5. Check Project Totals Before Confirmation

```bash
curl -s "$BASE_URL/projects/$PROJECT_ID"
```

Expected shape. Pending events do not affect totals:

```json
{
  "id": 1,
  "name": "Kitchen Remodel",
  "created_at": "2026-06-16T10:00:00",
  "updated_at": "2026-06-16T10:00:00",
  "totals": {
    "money_in": "0",
    "money_out": "0",
    "net": "0"
  }
}
```

## 6. List Pending Events

```bash
curl -s "$BASE_URL/projects/$PROJECT_ID/extracted-events/pending"
```

Expected shape:

```json
[
  {
    "id": 1,
    "project_id": 1,
    "raw_entry_id": 1,
    "type": "MONEY_IN",
    "counterparty_name": null,
    "counterparty_type": "UNKNOWN",
    "amount": "1200.00",
    "description": "Client paid me 1200 for cabinets",
    "event_date": null,
    "confidence": "0.5000",
    "status": "PENDING",
    "created_at": "2026-06-16T10:02:00",
    "updated_at": "2026-06-16T10:02:00"
  }
]
```

## 7. Edit Pending Event

```bash
curl -s -X PATCH "$BASE_URL/extracted-events/$EVENT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1250.00",
    "counterparty_name": "Client",
    "description": "Client payment for cabinets"
  }'
```

Expected shape:

```json
{
  "id": 1,
  "project_id": 1,
  "raw_entry_id": 1,
  "type": "MONEY_IN",
  "counterparty_name": "Client",
  "counterparty_type": "UNKNOWN",
  "amount": "1250.00",
  "description": "Client payment for cabinets",
  "event_date": null,
  "confidence": "0.5000",
  "status": "PENDING",
  "created_at": "2026-06-16T10:02:00",
  "updated_at": "2026-06-16T10:03:00"
}
```

## 8. Confirm Event

```bash
curl -s -X POST "$BASE_URL/extracted-events/$EVENT_ID/confirm"
```

Expected shape:

```json
{
  "id": 1,
  "project_id": 1,
  "raw_entry_id": 1,
  "type": "MONEY_IN",
  "counterparty_name": "Client",
  "counterparty_type": "UNKNOWN",
  "amount": "1250.00",
  "description": "Client payment for cabinets",
  "event_date": null,
  "confidence": "0.5000",
  "status": "CONFIRMED",
  "created_at": "2026-06-16T10:02:00",
  "updated_at": "2026-06-16T10:04:00"
}
```

## 9. Check Project Totals After Confirmation

```bash
curl -s "$BASE_URL/projects/$PROJECT_ID"
```

Expected shape. Confirmed `MONEY_IN` affects totals:

```json
{
  "id": 1,
  "name": "Kitchen Remodel",
  "created_at": "2026-06-16T10:00:00",
  "updated_at": "2026-06-16T10:00:00",
  "totals": {
    "money_in": "1250.00",
    "money_out": "0",
    "net": "1250.00"
  }
}
```

## 10. Create Unclear Note

```bash
curl -s -X POST "$BASE_URL/projects/$PROJECT_ID/raw-entries" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Talked to Dana about next week"
  }'
```

Expected shape:

```json
{
  "id": 2,
  "project_id": 1,
  "text": "Talked to Dana about next week",
  "status": "PENDING",
  "created_at": "2026-06-16T10:05:00",
  "updated_at": "2026-06-16T10:05:00"
}
```

Use the returned `id` as `NOTE_RAW_ENTRY_ID`:

```bash
NOTE_RAW_ENTRY_ID=2
```

## 11. Extract Unclear Note Into NOTE Event

```bash
curl -s -X POST "$BASE_URL/projects/$PROJECT_ID/raw-entries/$NOTE_RAW_ENTRY_ID/extract"
```

Expected shape:

```json
[
  {
    "id": 2,
    "project_id": 1,
    "raw_entry_id": 2,
    "type": "NOTE",
    "counterparty_name": null,
    "counterparty_type": "UNKNOWN",
    "amount": null,
    "description": "Talked to Dana about next week",
    "event_date": null,
    "confidence": "0.5000",
    "status": "PENDING",
    "created_at": "2026-06-16T10:06:00",
    "updated_at": "2026-06-16T10:06:00"
  }
]
```

Use the returned event `id` as `NOTE_EVENT_ID`:

```bash
NOTE_EVENT_ID=2
```

## 12. Discard Pending Event

```bash
curl -s -X POST "$BASE_URL/extracted-events/$NOTE_EVENT_ID/discard"
```

Expected shape:

```json
{
  "id": 2,
  "project_id": 1,
  "raw_entry_id": 2,
  "type": "NOTE",
  "counterparty_name": null,
  "counterparty_type": "UNKNOWN",
  "amount": null,
  "description": "Talked to Dana about next week",
  "event_date": null,
  "confidence": "0.5000",
  "status": "DISCARDED",
  "created_at": "2026-06-16T10:06:00",
  "updated_at": "2026-06-16T10:07:00"
}
```

Discarded events remain in the database for history and do not affect project totals.
