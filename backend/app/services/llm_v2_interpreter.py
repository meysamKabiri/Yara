import json
import os
import re
import time
import urllib.error
import urllib.request
from time import perf_counter
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core.observability_service import track_event, track_timed_event
from app.core.trace_context import get_trace_id
from app.services.input_normalizer import clean_entity_name
from app.services.persian_money_engine import normalize_text, parse_persian_money
from app.services.prompts.llm_v2_prompt import build_llm_v2_prompt

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "120"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))


def _emit_event(db: Session | None, event_name, payload=None, duration_ms=None):
    if db is None:
        return
    try:
        trace_id = get_trace_id()
        if trace_id:
            track_event(db=db, trace_id=trace_id, event_name=event_name, payload=payload, duration_ms=duration_ms)
    except Exception:
        pass


def _ollama_stats(body: dict[str, Any]) -> dict[str, int | float | None]:
    stats: dict[str, int | float | None] = {}
    for key in [
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    ]:
        value = body.get(key)
        stats[key] = value if isinstance(value, int | float) else None
        if key.endswith("_duration") and isinstance(value, int | float):
            stats[f"{key}_ms"] = round(value / 1_000_000, 1)
    return stats

VALID_INTENTS = {"SET_ROLE", "SETUP", "WORK", "FINANCIAL", "NOTE", "DOCUMENT"}
VALID_ACTIONS = {
    "SET_ROLE", "ADD_ENTITY", "UPDATE_ENTITY", "WORK_LOG",
    "PAYMENT_IN", "PAYMENT_OUT", "PURCHASE_PAID",
    "DEBT_CREATED", "CHECK_PAYMENT", "NOTE",
}
VALID_ENTITY_KINDS = {"PERSON", "COMPANY", "UNKNOWN"}
VALID_PROJECT_ROLES = {"CLIENT", "DAILY_WORKER", "SKILLED_WORKER", "VENDOR", "OTHER"}
VALID_DIRECTIONS = {"IN", "OUT", "NONE"}
VALID_PAYMENT_METHODS = {"CASH", "BANK_TRANSFER", "CHECK", "OTHER"}
VALID_WORK_UNITS = {"day", "meter", "item", "project", "custom"}
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_BARE_ENTITY_KEYS = {
    "name", "kind", "project_role", "role_detail",
    "phone", "account_number", "daily_rate", "notes", "field_updates",
}
_WRAPPER_KEYS = {"intent", "action", "entities", "financial", "work", "note"}


def _is_bare_entity(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if any(value.get(k) for k in _WRAPPER_KEYS):
        return False
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    overlap = _BARE_ENTITY_KEYS & set(value.keys())
    return len(overlap) >= 2


def _has_profile_fields(value: dict) -> bool:
    field_updates = value.get("field_updates") or {}
    if isinstance(field_updates, dict) and any(v not in (None, "") for v in field_updates.values()):
        return True
    return any(
        value.get(k) not in (None, "")
        for k in ("phone", "account_number", "daily_rate", "notes")
    )


_FINANCIAL_AMOUNT_UNITS = {"تومان", "تومن", "ریال", "هزار", "میلیون", "میلیارد"}

_FINANCIAL_PURCHASE_VERBS = {"خریدم", "خرید کردم", "فاکتور"}
_FINANCIAL_IN_VERBS = {
    "گرفتم", "گرفت", "دریافت", "دریافت کردم",
    "واریز", "واریز کرد", "واریز شده",
    "ریخت", "ریخت به حساب", "زد به حساب", "به حساب",
}
_FINANCIAL_OUT_VERBS = {"دادم", "داد", "پرداخت", "پرداخت کردم", "پول داد"}
_FINANCIAL_VERBS = _FINANCIAL_PURCHASE_VERBS | _FINANCIAL_IN_VERBS | _FINANCIAL_OUT_VERBS | {"چک", "بدهکار", "طلبکار"}


def _has_financial_signal(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    has_unit = any(u in normalized for u in _FINANCIAL_AMOUNT_UNITS)
    has_verb = any(v in normalized for v in _FINANCIAL_VERBS)
    if has_unit and has_verb:
        return True
    if has_unit and re.search(r"\d{4,}", normalized):
        return True
    return False


def _infer_financial_action(raw_text: str) -> str:
    normalized = normalize_text(raw_text)
    for verb in _FINANCIAL_PURCHASE_VERBS:
        if verb in normalized:
            return "PURCHASE_PAID"
    for verb in _FINANCIAL_IN_VERBS:
        if verb in normalized:
            return "PAYMENT_IN"
    for verb in _FINANCIAL_OUT_VERBS:
        if verb in normalized:
            return "PAYMENT_OUT"
    return "PAYMENT_IN"


def _wrap_bare_entity(value: dict, raw_text: str = "") -> dict:
    supported = {"name", "kind", "project_role", "role_detail", "phone", "account_number", "daily_rate", "notes", "field_updates"}
    clean = {k: v for k, v in value.items() if k in supported}

    if _has_profile_fields(value):
        return {
            "intent": "SETUP",
            "action": "UPDATE_ENTITY",
            "entities": [clean],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": float(value.get("confidence", 0.8) or 0.8),
            "ambiguity": bool(value.get("ambiguity")),
            "missing_fields": [],
            "reasoning_summary": str(value.get("reasoning_summary", "") or ""),
        }

    if raw_text and _has_financial_signal(raw_text):
        amount = parse_persian_money(raw_text)
        action = _infer_financial_action(raw_text)
        direction = "IN" if action == "PAYMENT_IN" else "OUT"
        return {
            "intent": "FINANCIAL",
            "action": action,
            "entities": [clean],
            "financial": {
                "amount": amount,
                "direction": direction,
                "payment_method": None,
                "due_date_text": None,
            },
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": float(value.get("confidence", 0.8) or 0.8),
            "ambiguity": bool(value.get("ambiguity")),
            "missing_fields": [],
            "reasoning_summary": str(value.get("reasoning_summary", "") or ""),
        }

    return {
        "intent": "SET_ROLE",
        "action": "SET_ROLE",
        "entities": [clean],
        "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": float(value.get("confidence", 0.8) or 0.8),
        "ambiguity": bool(value.get("ambiguity")),
        "missing_fields": [],
        "reasoning_summary": str(value.get("reasoning_summary", "") or ""),
    }


class LLMOutputParseError(ValueError):
    pass


class LLMv2Interpreter:
    def interpret(self, raw_text: str, project_id: int, db: Session | None = None) -> dict[str, Any]:
        if db is None:
            return self._interpret_impl(raw_text, project_id, db=None)
        return track_timed_event(
            db=db,
            event_name="llm_v2_interpreter.interpret",
            fn=lambda: self._interpret_impl(raw_text, project_id, db=db),
        )

    def _interpret_impl(self, raw_text: str, project_id: int, db: Session | None = None) -> dict[str, Any]:
        try:
            parsed = self._generate(raw_text, project_id, db=db)
            if not isinstance(parsed, dict):
                return self._fallback(raw_text, "model returned non-object JSON")

            normalize_start = perf_counter()
            result = self._coerce(parsed, raw_text)
            normalize_ms = (perf_counter() - normalize_start) * 1000

            _emit_event(db, "INTERPRETATION_NORMALIZED", {
                "stage": "LLM",
                "input_snapshot": raw_text,
                "output_snapshot": result,
                "normalized_result": result,
                "semantic_action": result.get("action"),
                "domain": result.get("intent"),
                "confidence": result.get("confidence"),
                "reasoning_summary": result.get("reasoning_summary"),
            }, duration_ms=normalize_ms)
            if isinstance(result.get("confidence"), int | float) and result["confidence"] < 0.5:
                _emit_event(db, "LLM_LOW_CONFIDENCE", {
                    "stage": "LLM",
                    "input_snapshot": raw_text,
                    "output_snapshot": result,
                    "domain": result.get("intent"),
                    "confidence": result.get("confidence"),
                    "reasoning_summary": result.get("reasoning_summary"),
                })

            timings = {
                "normalization_duration_ms": round(normalize_ms, 1),
                **(getattr(self, "_last_timings", {})),
            }
            result["_timings"] = timings
            return result
        except (OSError, TimeoutError, urllib.error.URLError, TypeError, LLMOutputParseError) as exc:
            _emit_event(db, "LLM_FAILED", {
                "stage": "LLM",
                "input_snapshot": raw_text,
                "error_message": str(exc),
                "failure_type": type(exc).__name__,
            })
            return self._fallback(raw_text, "shadow interpreter failed")

    def _generate(self, raw_text: str, project_id: int, db: Session | None = None) -> Any:
        prompt, prompt_domain = build_llm_v2_prompt(raw_text, project_id)
        _emit_event(db, "LLM_REQUEST_STARTED", {
            "stage": "LLM",
            "model": OLLAMA_MODEL,
            "timeout": OLLAMA_TIMEOUT_SECONDS,
            "num_predict": OLLAMA_NUM_PREDICT,
            "prompt_length": len(prompt),
            "prompt": prompt,
            "raw_text_length": len(raw_text),
            "prompt_domain": prompt_domain,
            "input_snapshot": prompt,
            "metadata": {
                "model": OLLAMA_MODEL,
                "timeout": OLLAMA_TIMEOUT_SECONDS,
                "num_predict": OLLAMA_NUM_PREDICT,
                "temperature": OLLAMA_TEMPERATURE,
                "prompt_domain": prompt_domain,
            },
        })
        ollama_start = perf_counter()

        payload = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "think": False,
                "options": {
                    "temperature": OLLAMA_TEMPERATURE,
                    "num_predict": OLLAMA_NUM_PREDICT,
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        attempt = 0
        max_attempts = 3
        while True:
            try:
                with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
                    ollama_body = json.loads(response.read().decode("utf-8"))
                break
            except (OSError, TimeoutError, urllib.error.URLError) as e:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                delay = min(0.5 * (2 ** attempt), 5.0)
                _emit_event(db, "LLM_RETRY", {
                    "attempt": attempt,
                    "error": str(e),
                    "max_attempts": max_attempts,
                })
                time.sleep(delay)
        ollama_ms = (perf_counter() - ollama_start) * 1000

        response_text = str(ollama_body.get("response", ""))
        thinking_text = str(ollama_body.get("thinking", ""))
        ollama_stats = _ollama_stats(ollama_body)
        _emit_event(db, "OLLAMA_RESPONSE_RECEIVED", {
            "stage": "LLM",
            "model": OLLAMA_MODEL,
            "prompt_domain": prompt_domain,
            "prompt_length": len(prompt),
            "response_length": len(response_text),
            "thinking_length": len(thinking_text),
            "raw_llm_output": response_text or thinking_text,
            "output_snapshot": response_text or thinking_text,
            **ollama_stats,
        }, duration_ms=ollama_ms)

        parse_start = perf_counter()
        try:
            parsed = self._parse_ollama_json(ollama_body)
        except LLMOutputParseError as exc:
            _emit_event(db, "LLM_JSON_PARSE_FAILED", {
                "stage": "LLM",
                "raw_llm_output": response_text or thinking_text,
                "output_snapshot": response_text or thinking_text,
                "error_message": str(exc),
                "failure_type": type(exc).__name__,
            }, duration_ms=(perf_counter() - parse_start) * 1000)
            raise
        parse_ms = (perf_counter() - parse_start) * 1000

        used_field = "response" if ollama_body.get("response") and str(ollama_body.get("response", "")).strip() else "thinking"
        _emit_event(db, "LLM_JSON_PARSED", {
            "stage": "LLM",
            "keys_parsed": list(parsed.keys()) if isinstance(parsed, dict) else [],
            "used_response_field": used_field,
            "parsed_json": parsed,
            "output_snapshot": parsed,
        }, duration_ms=parse_ms)

        self._last_timings = {
            "prompt_length": len(prompt),
            "raw_text_length": len(raw_text),
            "response_length": len(response_text),
            "thinking_length": len(thinking_text),
            "prompt_domain": prompt_domain,
            "ollama_http_duration_ms": round(ollama_ms, 1),
            "json_parse_duration_ms": round(parse_ms, 1),
            **ollama_stats,
        }
        return parsed

    def _parse_ollama_json(self, ollama_body: dict[str, Any]) -> Any:
        response_text = ollama_body.get("response")
        thinking_text = ollama_body.get("thinking")
        content = response_text if isinstance(response_text, str) and response_text.strip() else thinking_text
        if not isinstance(content, str) or not content.strip():
            raise LLMOutputParseError("Ollama returned empty response and thinking fields")
        return self._extract_json(content)

    def _extract_json(self, content: str) -> Any:
        text = content.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "{[":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise LLMOutputParseError("Ollama output did not contain a valid JSON object")

    def _coerce(self, value: dict[str, Any], raw_text: str = "") -> dict[str, Any]:
        events = value.get("events")
        if isinstance(events, list):
            coerced_events = []
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_text = event.get("matched_text") or raw_text
                coerced = self._coerce_single(event, event_text)
                if event.get("matched_text"):
                    coerced["matched_text"] = event["matched_text"]
                coerced_events.append(coerced)
            return {"events": coerced_events}
        return self._coerce_single(value, raw_text)

    def _coerce_single(self, value: dict[str, Any], raw_text: str = "") -> dict[str, Any]:
        if _is_bare_entity(value):
            value = _wrap_bare_entity(value, raw_text)
        intent = value.get("intent")
        action = value.get("action")
        raw_financial = value.get("financial")
        raw_work = value.get("work")
        raw_note = value.get("note")
        financial = cast("dict[str, Any]", raw_financial) if isinstance(raw_financial, dict) else {}
        work = cast("dict[str, Any]", raw_work) if isinstance(raw_work, dict) else {}
        note = cast("dict[str, Any]", raw_note) if isinstance(raw_note, dict) else {}
        direction = financial.get("direction")
        unit = work.get("unit")
        due_date_text = financial.get("due_date_text")
        work_description = work.get("description")
        note_text = note.get("text")

        entities = self._entities(value.get("entities"))
        self._normalize_profile_update_fields(raw_text, entities)
        if self._has_profile_update_fields(entities):
            intent = "SETUP"
            action = "UPDATE_ENTITY"
        elif raw_text and intent in {"SETUP", "SET_ROLE"} and _has_financial_signal(raw_text):
            amount = parse_persian_money(raw_text)
            if amount is not None:
                inferred_action = _infer_financial_action(raw_text)
                intent = "FINANCIAL"
                action = inferred_action
                financial["amount"] = amount
                direction = "IN" if inferred_action == "PAYMENT_IN" else "OUT"
                financial["direction"] = direction
                if financial.get("payment_method") not in VALID_PAYMENT_METHODS:
                    financial["payment_method"] = (
                        "BANK_TRANSFER"
                        if any(signal in normalize_text(raw_text) for signal in ["حساب", "کارت", "واریز", "انتقال", "بانکی", "ریخت"])
                        else None
                    )
                if entities:
                    if inferred_action == "PAYMENT_IN":
                        entities[0]["project_role"] = "CLIENT"
                    elif inferred_action == "PURCHASE_PAID":
                        entities[0]["project_role"] = "VENDOR"

        result = {
            "intent": intent if intent in VALID_INTENTS else "NOTE",
            "action": action if action in VALID_ACTIONS else self._action_for_intent(intent),
            "entities": entities,
            "financial": {
                "amount": self._number_or_none(financial.get("amount")),
                "direction": direction if direction in VALID_DIRECTIONS else "NONE",
                "payment_method": (
                    financial.get("payment_method")
                    if financial.get("payment_method") in VALID_PAYMENT_METHODS
                    else None
                ),
                "due_date_text": (
                    due_date_text.strip()
                    if isinstance(due_date_text, str) and due_date_text.strip()
                    else None
                ),
            },
            "work": {
                "quantity": self._number_or_none(work.get("quantity")),
                "unit": unit if unit in VALID_WORK_UNITS else None,
                "description": (
                    work_description.strip()
                    if isinstance(work_description, str) and work_description.strip()
                    else None
                ),
            },
            "note": {
                "text": (
                    note_text.strip()
                    if isinstance(note_text, str) and note_text.strip()
                    else None
                ),
            },
            "confidence": self._confidence(value.get("confidence")),
            "ambiguity": bool(value.get("ambiguity")),
            "missing_fields": self._missing_fields(value.get("missing_fields")),
            "reasoning_summary": str(
                value.get("reasoning_summary") or value.get("reasoning") or ""
            ),
        }
        if value.get("matched_text"):
            result["matched_text"] = value["matched_text"]
        return result

    def _action_for_intent(self, intent: Any) -> str:
        if intent == "SET_ROLE":
            return "SET_ROLE"
        if intent == "SETUP":
            return "ADD_ENTITY"
        if intent == "WORK":
            return "WORK_LOG"
        if intent == "FINANCIAL":
            return "PAYMENT_OUT"
        return "NOTE"

    def _entities(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        entities: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name") or "").strip()
            name = clean_entity_name(raw_name) or self._simple_safe_name(raw_name)
            if not name:
                continue
            kind = item.get("kind")
            project_role = item.get("project_role")
            role_detail = item.get("role_detail")
            phone = item.get("phone")
            account_number = item.get("account_number")
            daily_rate = item.get("daily_rate")
            notes = item.get("notes")
            field_updates = item.get("field_updates")
            entities.append(
                {
                    "name": name,
                    "kind": kind if kind in VALID_ENTITY_KINDS else "UNKNOWN",
                    "project_role": (
                        project_role if project_role in VALID_PROJECT_ROLES else "OTHER"
                    ),
                    "role_detail": (
                        str(role_detail).strip()
                        if isinstance(role_detail, str) and role_detail.strip()
                        else None
                    ),
                    "phone": (
                        str(phone).strip()
                        if isinstance(phone, str) and phone.strip()
                        else None
                    ),
                    "account_number": (
                        str(account_number).strip()
                        if isinstance(account_number, str) and account_number.strip()
                        else None
                    ),
                    "daily_rate": self._number_or_none(daily_rate),
                    "notes": (
                        str(notes).strip()
                        if isinstance(notes, str) and notes.strip()
                        else None
                    ),
                    "field_updates": field_updates if isinstance(field_updates, dict) else None,
                }
            )
        return entities

    def _simple_safe_name(self, value: str) -> str | None:
        if not value or re.search(r"[:：؛;,\-_/|\d]", value):
            return None
        normalized = re.sub(r"\s+", " ", value).strip()
        return normalized if normalized else None

    def _number_or_none(self, value: Any) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    def _confidence(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return 0.0
        return max(0.0, min(float(value), 1.0))

    def _missing_fields(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _normalize_profile_update_fields(self, raw_text: str, entities: list[dict[str, Any]]) -> None:
        normalized_text = " ".join((raw_text or "").replace("\u200c", " ").split())
        compact_text = normalized_text.translate(PERSIAN_DIGITS).replace(" ", "")
        account_number = (
            self._longest_digit_sequence(compact_text, min_length=8, max_length=26)
            if self._has_account_intent(normalized_text)
            else None
        )
        phone = self._phone_sequence(compact_text) if self._has_phone_intent(normalized_text) else None
        if not entities:
            name = self._profile_update_name(normalized_text, [account_number, phone])
            if name is None or (account_number is None and phone is None):
                return
            entities.append(
                {
                    "name": name,
                    "kind": "PERSON",
                    "project_role": "OTHER",
                    "role_detail": None,
                    "phone": None,
                    "account_number": None,
                    "daily_rate": None,
                    "notes": None,
                    "field_updates": {},
                }
            )
        first_entity = entities[0]
        field_updates = first_entity.get("field_updates")
        if not isinstance(field_updates, dict):
            field_updates = {}
            first_entity["field_updates"] = field_updates

        if self._has_account_intent(normalized_text) and not first_entity.get("account_number"):
            if account_number is not None:
                first_entity["account_number"] = account_number
                field_updates["account_number"] = account_number

        if self._has_phone_intent(normalized_text) and not first_entity.get("phone"):
            if phone is not None:
                first_entity["phone"] = phone
                field_updates["phone"] = phone

        if not field_updates:
            first_entity["field_updates"] = None

    def _has_profile_update_fields(self, entities: list[dict[str, Any]]) -> bool:
        for entity in entities:
            field_updates = entity.get("field_updates")
            if isinstance(field_updates, dict) and any(value not in (None, "") for value in field_updates.values()):
                return True
            if any(entity.get(key) not in (None, "") for key in ("phone", "account_number", "daily_rate", "notes")):
                return True
        return False

    def _has_account_intent(self, text: str) -> bool:
        normalized = text.lower()
        return any(
            term in normalized
            for term in ("شماره حساب", "شماره کارت", "حساب", "کارت", "شبا", "account", "card")
        )

    def _has_phone_intent(self, text: str) -> bool:
        normalized = text.lower()
        return any(
            term in normalized
            for term in ("شماره تماس", "شماره موبایل", "موبایل", "تلفن", "phone", "mobile")
        )

    def _longest_digit_sequence(self, text: str, *, min_length: int, max_length: int) -> str | None:
        matches = [match.group() for match in re.finditer(r"\d+", text)]
        candidates = [match for match in matches if min_length <= len(match) <= max_length]
        if not candidates:
            return None
        return max(candidates, key=len)

    def _phone_sequence(self, text: str) -> str | None:
        match = re.search(r"09\d{5,12}", text)
        return match.group() if match is not None else None

    def _profile_update_name(self, text: str, values: list[str | None]) -> str | None:
        candidate = text
        for value in values:
            if value:
                candidate = candidate.replace(value, " ")
        candidate = re.sub(r"[۰-۹٠-٩0-9]{4,}", " ", candidate)
        candidate = re.sub(
            r"شماره\s+حساب|شماره\s+کارت|شماره\s+تماس|شماره\s+موبایل|حساب|کارت|شبا|موبایل|تلفن|iban|account|card|phone|mobile|برای|به",
            " ",
            candidate,
            flags=re.IGNORECASE,
        )
        name = re.sub(r"\s+", " ", candidate).strip()
        return name or None

    def _fallback(self, raw_text: str, reason: str) -> dict[str, Any]:
        return {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {
                "amount": None, "direction": "NONE",
                "payment_method": None, "due_date_text": None,
            },
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": raw_text},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": f"{reason}: {raw_text}",
            "_llm_v2_failed": True,
        }
