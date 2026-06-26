#!/usr/bin/env python3
import json
import os
import time
import urllib.request


BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")


def main() -> None:
    payload = {
        "model": MODEL,
        "prompt": "/no_think\nReturn only valid JSON.\n{\"ok\":true}",
        "format": "json",
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 20,
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
    print(json.dumps({
        "model": MODEL,
        "base_url": BASE_URL,
        "duration_sec": round(duration_sec, 3),
        "response_preview": response_text[:200],
        "thinking_empty": thinking_text == "",
        "thinking_length": len(thinking_text),
        "load_duration_ms": _ns_to_ms(body.get("load_duration")),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
    }, ensure_ascii=False, indent=2))


def _ns_to_ms(value):
    return round(value / 1_000_000, 1) if isinstance(value, int | float) else None


if __name__ == "__main__":
    main()
