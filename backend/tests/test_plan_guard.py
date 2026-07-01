# ruff: noqa: E402, I001

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_guard import format_result, load_plan, validate_request


def test_plan_guard_allows_plan_aligned_project_scoped_task_change():
    result = validate_request(
        "Add project-scoped task due dates that still use modal confirmation.",
        load_plan(),
    )

    assert result.compliance == "COMPLIANT"
    assert result.domains == ["TASK"]
    assert result.risk_level == "LOW"
    assert result.recommended_action == "proceed"


def test_plan_guard_rejects_forbidden_global_task_system():
    result = validate_request("Create a global task dashboard across all projects.", load_plan())

    assert result.compliance == "NON-COMPLIANT"
    assert "Global task system" in result.impacted_rules
    assert result.risk_level in {"MEDIUM", "HIGH"}
    assert result.recommended_action in {"modify", "reject"}


def test_plan_guard_output_contains_required_validation_fields():
    result = validate_request("Skip confirmation for payments.", load_plan())

    output = format_result(result)

    assert "PLAN COMPATIBILITY RESULT: NON-COMPLIANT" in output
    assert "RULES IMPACTED:" in output
    assert "RISK LEVEL:" in output
    assert "RECOMMENDED ACTION:" in output
