import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.api import projects as project_api
from app.db.session import SessionLocal
from app.models.core import HistoryEntry, Invoice, Payment, Project, Worker, WorkerState
from app.schemas.projects import NaturalInputCreate, PendingInterpretationConfirm, ProjectCreate
from app.services.entity_normalizer import normalize_name
from app.services.persian_money_engine import parse_persian_money
from dev_tools.sandbox.scenarios import get_scenario

STATUS_PATH = Path(__file__).with_name("last_status.json")


def seed_sandbox_data(name: str = "villa_project_basic") -> dict[str, Any]:
    scenario = get_scenario(name)
    return _run_steps(name, scenario["setup"], write_status=False)


def replay_scenario(name: str = "villa_project_basic") -> dict[str, Any]:
    scenario = get_scenario(name)
    return _run_steps(name, scenario["messages"], write_status=True)


def run_sandbox_pipeline(name: str = "villa_project_basic") -> dict[str, Any]:
    scenario = get_scenario(name)
    return _run_steps(name, [*scenario["setup"], *scenario["messages"]], write_status=True)


def seed_scenario(name: str = "villa_project_basic") -> dict[str, Any]:
    return run_sandbox_pipeline(name)


def _run_steps(
    name: str,
    steps: list[dict[str, Any]],
    *,
    write_status: bool,
) -> dict[str, Any]:
    scenario = get_scenario(name)
    graphs_by_text = {step["text"]: step["graph"] for step in steps}
    original_extract_graph = project_api.extract_graph
    original_llm_v2_interpret = project_api.LLMv2Interpreter.interpret
    project_api.extract_graph = lambda text: graphs_by_text[text]
    project_api.LLMv2Interpreter.interpret = lambda self, text, project_id: _llm_v2_from_graph(
        text,
        graphs_by_text[text],
    )

    try:
        with SessionLocal() as db:
            project = _get_or_create_project(db, scenario["project_name"])
            trace = []
            for step in steps:
                draft = project_api.process_natural_input(
                    project.id,
                    NaturalInputCreate(text=step["text"]),
                    db,
                )
                confirmed_results = [
                    _confirm_interpretation(db, interpretation)
                    for interpretation in draft.interpretations
                ]
                trace.append(
                    {
                        "input_text": step["text"],
                        "detected_intents": [result.intent for result in confirmed_results],
                        "entities": [
                            worker.name
                            for result in confirmed_results
                            for worker in result.workers
                        ],
                        "states": [
                            state.name
                            for result in confirmed_results
                            for state in result.states
                        ],
                        "history_entries": [
                            entry.id
                            for result in confirmed_results
                            for entry in result.history_entries
                        ],
                    }
                )

            status = _build_status(db, project, name, trace)
            if write_status:
                STATUS_PATH.write_text(
                    json.dumps(status, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return status
    finally:
        project_api.extract_graph = original_extract_graph
        project_api.LLMv2Interpreter.interpret = original_llm_v2_interpret


def _confirmation_payload_for_interpretation(db, interpretation) -> PendingInterpretationConfirm:
    entity_name = None
    entities = interpretation.extracted_entities or []
    if entities and isinstance(entities[0].get("name"), str):
        entity_name = entities[0]["name"]
    if entity_name:
        normalized = normalize_name(entity_name)
        matches = [
            worker
            for worker in db.scalars(select(Worker).where(Worker.project_id == interpretation.project_id))
            if normalize_name(worker.name) == normalized
        ]
        if len(matches) == 1:
            return PendingInterpretationConfirm(selected_person_id=matches[0].id)
    if interpretation.canonical_event_type == "SETUP_EVENT" or _pending_entity_is_vendor(interpretation):
        return PendingInterpretationConfirm(create_new=True)
    return PendingInterpretationConfirm()


def _confirm_interpretation(db, interpretation):
    result = project_api.confirm_pending_interpretation(
        interpretation.id,
        db,
        _confirmation_payload_for_interpretation(db, interpretation),
    )
    if getattr(result, "status", None) == "ENTITY_RESOLVED":
        result = project_api.confirm_pending_interpretation(
            interpretation.id,
            db,
            PendingInterpretationConfirm(entity_id=result.entity_id, confirmed=True),
        )
    return result


def _pending_entity_is_vendor(interpretation) -> bool:
    entities = interpretation.extracted_entities or []
    if not entities:
        return False
    role = entities[0].get("project_role") or entities[0].get("type")
    return role == "VENDOR"


def _llm_v2_from_graph(text: str, graph: dict[str, Any]) -> dict[str, Any]:
    intent = graph.get("intent")
    entities = _llm_v2_entities(graph)
    amount = parse_persian_money(text)
    if intent == "SETUP":
        return _llm_v2_payload(
            intent="SETUP",
            action="ADD_ENTITY",
            entities=entities,
            reasoning_summary="sandbox setup",
        )
    if intent == "WORK":
        entity_name = graph.get("entity") if isinstance(graph.get("entity"), str) else None
        return _llm_v2_payload(
            intent="WORK",
            action="WORK_LOG",
            entities=entities or [_llm_v2_entity(entity_name or "طرف حساب نامشخص", "DAILY_WORKER", None)],
            work={"quantity": _quantity_from_text(text), "unit": "meter" if "متر" in text else None, "description": text},
            reasoning_summary="sandbox work",
        )
    if intent in {"PAYMENT", "INVOICE"}:
        entity_name = graph.get("entity") if isinstance(graph.get("entity"), str) else None
        action = "PURCHASE_PAID" if "خرید" in text else "PAYMENT_OUT"
        if "چک" in text:
            action = "CHECK_PAYMENT"
        return _llm_v2_payload(
            intent="FINANCIAL",
            action=action,
            entities=entities or [_llm_v2_entity(entity_name or "طرف حساب نامشخص", "VENDOR", None)],
            financial={
                "amount": amount,
                "direction": "OUT",
                "payment_method": "CHECK" if "چک" in text else "BANK_TRANSFER",
                "due_date_text": None,
            },
            reasoning_summary="sandbox financial",
        )
    return _llm_v2_payload(
        intent="NOTE",
        action="NOTE",
        entities=entities,
        note={"text": text},
        reasoning_summary="sandbox note",
    )


def _llm_v2_payload(
    *,
    intent: str,
    action: str,
    entities: list[dict[str, Any]],
    financial: dict[str, Any] | None = None,
    work: dict[str, Any] | None = None,
    note: dict[str, Any] | None = None,
    reasoning_summary: str,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "action": action,
        "entities": entities,
        "financial": financial or {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
        "work": work or {"quantity": None, "unit": None, "description": None},
        "note": note or {"text": None},
        "confidence": 1,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": reasoning_summary,
    }


def _llm_v2_entities(graph: dict[str, Any]) -> list[dict[str, Any]]:
    entities = graph.get("entities")
    if isinstance(entities, list):
        return [
            _llm_v2_entity(
                str(entity.get("name")),
                _graph_role_to_llm_role(entity.get("type")),
                entity.get("role_detail") if isinstance(entity.get("role_detail"), str) else None,
            )
            for entity in entities
            if isinstance(entity, dict) and entity.get("name")
        ]
    entity_name = graph.get("entity")
    if isinstance(entity_name, str) and entity_name.strip():
        return [_llm_v2_entity(entity_name.strip(), "DAILY_WORKER", None)]
    return []


def _llm_v2_entity(name: str, project_role: str, role_detail: str | None) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "PERSON" if project_role != "VENDOR" else "COMPANY",
        "project_role": project_role,
        "role_detail": role_detail,
    }


def _graph_role_to_llm_role(value: Any) -> str:
    if value == "CLIENT":
        return "CLIENT"
    if value == "VENDOR":
        return "VENDOR"
    return "SKILLED_WORKER" if value == "SKILLED_WORKER" else "DAILY_WORKER"


def _quantity_from_text(text: str) -> int | None:
    for token in text.split():
        if token.isdigit():
            return int(token)
    if "۲۰" in text:
        return 20
    return None


def _get_or_create_project(db, project_name: str) -> Project:
    project = db.scalar(select(Project).where(Project.name == project_name))
    if project is not None:
        return project
    return project_api.create_project(ProjectCreate(name=project_name), db)


def _build_status(
    db,
    project: Project,
    scenario_name: str,
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    workers = list(db.scalars(select(Worker).where(Worker.project_id == project.id)))
    states = list(db.scalars(select(WorkerState).where(WorkerState.project_id == project.id)))
    invoices = list(db.scalars(select(Invoice).where(Invoice.project_id == project.id)))
    payments = list(db.scalars(select(Payment).where(Payment.project_id == project.id)))
    history = list(db.scalars(select(HistoryEntry).where(HistoryEntry.project_id == project.id)))
    return {
        "scenario": scenario_name,
        "project": {"id": project.id, "name": project.name},
        "entity_registry": [
            {
                "id": worker.id,
                "name": worker.name,
                "type": worker.type.value,
                "phone": worker.phone,
                "role_detail": worker.role_detail,
            }
            for worker in workers
        ],
        "worker_states": [
            {
                "name": state.name,
                "role": state.role.value,
                "total_days_worked": str(state.total_days_worked),
                "total_quantity": str(state.total_quantity),
                "unit": state.unit,
                "financial_balance": str(state.financial_balance),
            }
            for state in states
        ],
        "invoices_summary": [
            {
                "vendor_id": invoice.vendor_id,
                "amount": str(invoice.total_amount),
                "status": invoice.status.value,
            }
            for invoice in invoices
        ],
        "payments_summary": [
            {
                "entity_id": payment.entity_id,
                "amount": str(payment.amount),
                "type": payment.type.value,
                "direction": payment.direction.value,
            }
            for payment in payments
        ],
        "history_count": len(history),
        "trace": trace,
    }


if __name__ == "__main__":
    seed_scenario(sys.argv[1] if len(sys.argv) > 1 else "villa_project_basic")
