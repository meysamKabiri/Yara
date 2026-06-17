import json
from pathlib import Path
from typing import Any

from app.core.semantic_rules import CanonicalEvent
from app.dev_tools.semantic_firewall.firewall import (
    FirewallDecision,
    SemanticFirewallError,
    SemanticFirewallService,
)
from app.dev_tools.semantic_firewall.test_cases import SEMANTIC_TEST_CASES
from app.models.core import Worker, WorkerType
from app.services.llm_extraction import extract_graph
from app.services.semantic_normalizer import SemanticNormalizerService

FAILURES_PATH = Path(__file__).with_name("semantic_failures.json")


def run_semantic_tests() -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for index, test_case in enumerate(SEMANTIC_TEST_CASES, start=1):
        result = _run_case(index, test_case)
        results.append(result)
        if not result["passed"]:
            failures.append(result)

    if failures:
        FAILURES_PATH.write_text(
            json.dumps(failures, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif FAILURES_PATH.exists():
        FAILURES_PATH.unlink()

    summary = {"passed": len(results) - len(failures), "failed": len(failures), "results": results}
    print(f"[SUMMARY] {summary['passed']} passed, {summary['failed']} failed")
    if failures:
        raise SystemExit(1)
    return summary


def _run_case(index: int, test_case: dict[str, Any]) -> dict[str, Any]:
    raw_text = test_case["input"]
    context = _context_entities(test_case.get("context_entities", []))
    llm_output = extract_graph(raw_text)
    normalized = SemanticNormalizerService().normalize(llm_output, raw_text, context)

    try:
        decision = SemanticFirewallService().validate(normalized, raw_text, context, llm_output)
    except SemanticFirewallError as exc:
        result = _result(index, test_case, llm_output, normalized, None, False, str(exc))
        _print_result(result)
        return result

    passed, reason = _matches_expected(test_case, decision)
    result = _result(index, test_case, llm_output, normalized, decision, passed, reason)
    _print_result(result)
    return result


def _matches_expected(test_case: dict[str, Any], decision: FirewallDecision) -> tuple[bool, str]:
    event = decision.event
    expected_type = test_case["expected_event_type"]
    expected_entity = test_case.get("expected_entity")
    expected_action = test_case.get("expected_action")

    if event.type.value != expected_type:
        return False, f"expected {expected_type} but got {event.type.value}"
    if expected_action is not None and event.action != expected_action:
        return False, f"expected action {expected_action} but got {event.action}"
    if expected_entity is not None and event.entity_name != expected_entity:
        return False, f"expected entity {expected_entity} but got {event.entity_name}"
    if event.type.value == "WORK_EVENT" and event.entity_name is None:
        return False, "WORK_EVENT requires a resolved entity"
    return True, decision.reason


def _print_result(result: dict[str, Any]) -> None:
    if result["passed"] and result["firewall_status"] == "FIXED":
        print(f"[FIXED] {result['name']}: {result['firewall_reason']}")
    elif result["passed"]:
        print(f"[PASS] {result['name']}: {result['actual_event_type']} detected correctly")
    else:
        print(f"[FAIL] {result['name']}: {result['reason']}")


def _result(
    index: int,
    test_case: dict[str, Any],
    llm_output: dict[str, Any],
    normalized: CanonicalEvent,
    decision: FirewallDecision | None,
    passed: bool,
    reason: str,
) -> dict[str, Any]:
    final_event = decision.event if decision is not None else normalized
    return {
        "index": index,
        "name": test_case["name"],
        "input": test_case["input"],
        "expected_event_type": test_case["expected_event_type"],
        "expected_entity": test_case.get("expected_entity"),
        "actual_event_type": final_event.type.value,
        "actual_action": final_event.action,
        "actual_entity": final_event.entity_name,
        "passed": passed,
        "reason": reason,
        "llm_output": llm_output,
        "normalized_event": _event_snapshot(normalized),
        "firewall_status": decision.status if decision is not None else "BLOCKED",
        "firewall_reason": decision.reason if decision is not None else reason,
        "firewall_event": _event_snapshot(final_event),
    }


def _event_snapshot(event: CanonicalEvent) -> dict[str, Any]:
    return {
        "type": event.type.value,
        "entity_id": event.entity_id,
        "entity_name": event.entity_name,
        "action": event.action,
        "delta": str(event.delta) if event.delta is not None else None,
        "metadata": event.metadata,
    }


def _context_entities(names: list[str]) -> list[Worker]:
    return [
        Worker(id=index, project_id=1, name=name, type=_entity_type(name))
        for index, name in enumerate(names, start=1)
    ]


def _entity_type(name: str) -> WorkerType:
    if name == "میثم کبیری":
        return WorkerType.CLIENT
    if "هادی" in name:
        return WorkerType.VENDOR
    if "جوشکار" in name:
        return WorkerType.SKILLED_WORKER
    return WorkerType.DAILY_WORKER


if __name__ == "__main__":
    run_semantic_tests()
