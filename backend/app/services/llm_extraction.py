import json
import urllib.error
import urllib.request
from typing import Any

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"

SYSTEM_PROMPT = """You are a financial extraction engine.

Your task is to extract raw construction work and financial intents from Persian and English
contractor notes.

Return ONLY valid JSON array. No explanations. No markdown.

Each item must follow this schema:

{
"type": "WORK_LOG | PAYMENT | INVOICE | NOTE",
"entity_name": string | null,
"amount_text": string | null,
"unit": "meter | day | item" | null,
"quantity_text": string | null,
"description": string,
"confidence": number (0 to 1)
}

Rules:

* If multiple work or financial activities exist, return multiple items.
* If the text is unclear or not financial, return a single NOTE event.
* Extract money amounts only as the exact raw text span in amount_text.
* Extract work quantity only as the exact raw text span in quantity_text.
* Do NOT output numeric amounts.
* Do NOT calculate, scale, or convert million/thousand values.
* Do NOT calculate totals.
* Do NOT merge multiple activities.
* Do NOT guess missing amounts or names.
* Do NOT include any extra text.
* Output must be valid JSON only."""

GRAPH_PROMPT = """You are a construction finance graph extraction engine.

Your task is to convert Persian and English contractor notes into raw structured intent.

Return ONLY valid JSON object. No explanations. No markdown.

The object must follow this schema:

{
"intent": "SETUP | ENTITY_UPDATE | WORK | PAYMENT | INVOICE | NOTE",
"entity": string | null,
"entities": [
{
"type": "CLIENT | WORKER | VENDOR",
"name": string,
"phone": string | null,
"account_number": string | null,
"role_detail": string | null,
"field_updates": {
"phone": string | null,
"account_number": string | null,
"role_detail": string | null
}
}
],
"action": "INCREMENT | SET | PAYMENT | INVOICE",
"confidence": number (0 to 1)
}

Rules:

* Extract intent and entity name only.
* Use SETUP when the input defines a project owner, client, worker, vendor, phone number,
  account number, or role detail.
* Use ENTITY_UPDATE when the input adds phone, account number, or role detail for an
  existing entity.
* For SETUP, fill entities with every entity mentioned.
* For ENTITY_UPDATE, include the entity name and field_updates.
* Prefer ENTITY_UPDATE over NOTE when entity context exists.
* Do NOT calculate totals.
* Do NOT convert money values to numbers.
* Do NOT convert work quantities to numbers.
* Do NOT ask for structured data.
* If unclear, return intent NOTE.
* Output must be valid JSON only."""


def extract(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "prompt": f"{SYSTEM_PROMPT}\n\nNote:\n{text}",
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            ollama_body = json.loads(response.read().decode("utf-8"))

        events = json.loads(ollama_body.get("response", ""))
        if not isinstance(events, list):
            return _fallback_note(text)
        return events
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, TypeError):
        return _fallback_note(text)


def extract_graph(text: str) -> dict[str, Any]:
    try:
        parsed = _generate_json(GRAPH_PROMPT, text)
        if not isinstance(parsed, dict):
            return _fallback_graph_note(text)
        return parsed
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, TypeError):
        return _fallback_graph_note(text)


def _generate_json(prompt: str, text: str) -> Any:
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": f"{prompt}\n\nNote:\n{text}",
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        ollama_body = json.loads(response.read().decode("utf-8"))

    return json.loads(ollama_body.get("response", ""))


def _fallback_note(text: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "NOTE",
            "entity_name": None,
            "amount_text": None,
            "unit": None,
            "quantity_text": None,
            "description": text,
            "confidence": 0.3,
        }
    ]


def _fallback_graph_note(text: str) -> dict[str, Any]:
    return {
        "intent": "NOTE",
        "entity": None,
        "entities": [],
        "action": "SET",
        "confidence": 0.3,
    }
