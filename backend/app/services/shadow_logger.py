from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models.core import ShadowInterpretationLog
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow


def log_shadow_comparison(
    project_id: int,
    input_text: str,
    legacy_result: dict[str, Any] | list[dict[str, Any]],
    shadow_result: dict[str, Any],
    db: Session | None = None,
) -> dict[str, bool]:
    diff = compare_legacy_vs_shadow(legacy_result, shadow_result)
    if db is not None:
        db.add(
            ShadowInterpretationLog(
                project_id=project_id,
                input_text=input_text,
                legacy_json=jsonable_encoder(legacy_result),
                shadow_json=jsonable_encoder(shadow_result),
                diff_json=diff,
            )
        )
        db.commit()
    return diff
