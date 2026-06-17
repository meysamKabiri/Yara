import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.api import projects as project_api
from app.db.session import SessionLocal
from app.models.core import HistoryEntry, Invoice, Payment, Project, Worker, WorkerState
from app.schemas.projects import NaturalInputCreate, ProjectCreate
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
    project_api.extract_graph = lambda text: graphs_by_text[text]

    try:
        with SessionLocal() as db:
            project = _get_or_create_project(db, scenario["project_name"])
            trace = []
            for step in steps:
                result = project_api.process_natural_input(
                    project.id,
                    NaturalInputCreate(text=step["text"]),
                    db,
                )
                trace.append(
                    {
                        "input_text": step["text"],
                        "detected_intent": result.intent,
                        "entities": [worker.name for worker in result.workers],
                        "states": [state.name for state in result.states],
                        "history_entries": [entry.id for entry in result.history_entries],
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
            }
            for payment in payments
        ],
        "history_count": len(history),
        "trace": trace,
    }


if __name__ == "__main__":
    seed_scenario(sys.argv[1] if len(sys.argv) > 1 else "villa_project_basic")
