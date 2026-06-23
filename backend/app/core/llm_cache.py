from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any


MAX_LLM_CACHE_SIZE = 512
_LLM_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_LLM_CACHE_LOCK = threading.Lock()


def llm_cache_key(input_text: str, project_id: int, context: dict[str, Any] | None = None) -> str:
    raw = json.dumps(
        {
            "input": input_text.strip(),
            "project_id": project_id,
            "context": context or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_llm_cache(key: str) -> dict[str, Any] | None:
    with _LLM_CACHE_LOCK:
        cached = _LLM_CACHE.get(key)
        if cached is None:
            return None
        _LLM_CACHE.move_to_end(key)
        return copy.deepcopy(cached)


def set_llm_cache(key: str, value: dict[str, Any]) -> dict[str, Any]:
    with _LLM_CACHE_LOCK:
        _LLM_CACHE[key] = copy.deepcopy(value)
        _LLM_CACHE.move_to_end(key)
        while len(_LLM_CACHE) > MAX_LLM_CACHE_SIZE:
            _LLM_CACHE.popitem(last=False)
    return value
