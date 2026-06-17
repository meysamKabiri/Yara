import json
import urllib.error
import urllib.request
from typing import Any

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"

SYSTEM_PROMPT = """You are a raw contractor note extraction engine.

Your task is to extract raw spans from Persian and English contractor notes.
Do not classify business meaning.

Return ONLY valid JSON array. No explanations. No markdown.

Each item must follow this schema:

{
"raw_type": string | null,
"entity_name": string | null,
"amount_text": string | null,
"unit": "meter | day | item" | null,
"quantity_text": string | null,
"description": string,
"confidence": number (0 to 1)
}

Rules:

* If multiple raw activities exist, return multiple items.
* Extract money amounts only as the exact raw text span in amount_text.
* Extract work quantity only as the exact raw text span in quantity_text.
* Do NOT output numeric amounts.
* Do NOT calculate, scale, or convert million/thousand values.
* Do NOT calculate totals.
* Do NOT classify as work, financial, setup, or note.
* Do NOT merge multiple raw activities.
* Do NOT guess missing amounts or names.
* Do NOT include any extra text.
* Output must be valid JSON only."""

GRAPH_PROMPT = """You are a raw construction note graph extraction engine.

Your task is to extract raw entities and raw context from Persian and English contractor notes.
Do not classify business meaning. The application has a deterministic rule engine for that.

Return ONLY valid JSON object. No explanations. No markdown.

The object must follow this schema:

{
"raw_intent": string | null,
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
"raw_context": string,
"confidence": number (0 to 1)
}

Rules:

* Extract entity names and raw field spans only.
* Fill entities with every entity mentioned.
* Include field_updates only when raw phone, account number, or role detail appears.
* Do NOT calculate totals.
* Do NOT convert money values to numbers.
* Do NOT convert work quantities to numbers.
* Do NOT classify the note as work, financial, setup, entity update, or note.
* Do NOT ask for structured data.
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
            "raw_type": None,
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
        "raw_intent": None,
        "entity": None,
        "entities": [],
        "raw_context": text,
        "confidence": 0.3,
    }
