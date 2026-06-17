import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["sandbox"])
STATUS_PATH = Path(__file__).parents[2] / "dev_tools" / "sandbox" / "last_status.json"


@router.get("/sandbox/status")
def get_sandbox_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {"last_scenario_run": None, "status": "not_run"}
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    return {"last_scenario_run": status.get("scenario"), "status": status}
