from app.core.role_registry import (
    detect_role_label,
    is_skilled_role_text,
    labels_for_project_role,
    registry_key_to_project_role,
    role_token_map,
)


def test_role_registry_contains_required_skilled_trade_labels() -> None:
    labels = labels_for_project_role("SKILLED_WORKER")

    assert "نقاش" in labels
    assert "گچ کار" in labels
    assert "کابینت کار" in labels
    assert "جوشکار" in labels


def test_registry_maps_general_worker_to_existing_worker_type() -> None:
    assert registry_key_to_project_role("GENERAL_WORKER") == "DAILY_WORKER"
    assert role_token_map()["کارگر"] == "DAILY_WORKER"


def test_registry_detects_role_labels_from_text() -> None:
    assert detect_role_label("کاظمی نقاش به پروژه اضافه شد") == ("نقاش", "SKILLED_WORKER")
    assert is_skilled_role_text("احمدی کابینت کار است")
