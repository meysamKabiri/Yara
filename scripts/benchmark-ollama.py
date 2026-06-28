#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.prompts.llm_v2_prompt import build_llm_v2_prompt  # noqa: E402


BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "120"))
PURCHASE_TEXT = "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم"


def main() -> None:
    actual_prompt, domain = build_llm_v2_prompt(PURCHASE_TEXT, 1)
    cases = [
        (
            "tiny_json_ping",
            "/no_think\nReturn only valid JSON.\n{\"ok\":true}",
            20,
        ),
        (
            "purchase_extraction_small",
            "/no_think\nReturn only valid JSON. Extract purchase as JSON with action, amount, role, direction, payment_method.\n"
            f"Text: {PURCHASE_TEXT}",
            NUM_PREDICT,
        ),
        (
            f"actual_app_prompt_{domain}",
            actual_prompt,
            NUM_PREDICT,
        ),
    ]
    results = [run_case(name, prompt, num_predict) for name, prompt, num_predict in cases]
    print(json.dumps(results, ensure_ascii=False, indent=2))


def run_case(name: str, prompt: str, num_predict: int) -> dict:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
        },
    }
    start = time.perf_counter()
    request = urllib.request.Request(
        f"{BASE_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    duration_sec = time.perf_counter() - start
    response_text = str(body.get("response", ""))
    thinking_text = str(body.get("thinking", ""))
    valid_json = True
    try:
        json.loads(response_text)
    except json.JSONDecodeError:
        valid_json = False
    return {
        "name": name,
        "model": MODEL,
        "base_url": BASE_URL,
        "duration_sec": round(duration_sec, 3),
        "prompt_length": len(prompt),
        "response_length": len(response_text),
        "valid_json": valid_json,
        "thinking_length": len(thinking_text),
        "load_duration_ms": _ns_to_ms(body.get("load_duration")),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "prompt_eval_duration_ms": _ns_to_ms(body.get("prompt_eval_duration")),
        "eval_count": body.get("eval_count"),
        "eval_duration_ms": _ns_to_ms(body.get("eval_duration")),
        "total_duration_ms": _ns_to_ms(body.get("total_duration")),
        "response_preview": response_text[:200],
    }


def _ns_to_ms(value):
    return round(value / 1_000_000, 1) if isinstance(value, int | float) else None


if __name__ == "__main__":
    main()
