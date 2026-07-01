from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.core import PendingInterpretation
from app.services.domain_router_service import DomainRouterService


def pending_route_input(interpretation: PendingInterpretation) -> dict[str, Any]:
    route_input: dict[str, Any] = {
        "semantic_action": interpretation.semantic_action,
        "action": interpretation.semantic_action,
        "entities": interpretation.extracted_entities or [],
        "extracted_entities": interpretation.extracted_entities or [],
        "financial": {
            "amount": interpretation.extracted_amount,
            "direction": interpretation.financial_direction.value if interpretation.financial_direction is not None else None,
        },
    }
    if isinstance(interpretation.structured_interpretation, dict):
        route_input.update(interpretation.structured_interpretation)
        route_input.setdefault("semantic_action", interpretation.semantic_action)
        route_input.setdefault("action", interpretation.semantic_action)
        if not route_input.get("entities"):
            route_input["entities"] = interpretation.extracted_entities or []
        if not route_input.get("extracted_entities"):
            route_input["extracted_entities"] = interpretation.extracted_entities or []
    return route_input


def resolve_pending_domain_route(
    interpretation: PendingInterpretation,
    db: Session | None = None,
) -> dict[str, Any]:
    if isinstance(interpretation.domain_route, dict) and interpretation.domain_route:
        return interpretation.domain_route

    return DomainRouterService().route(
        interpretation.raw_input_text,
        pending_route_input(interpretation),
        db=db,
    )


def stamp_pending_domain_route(
    interpretation: PendingInterpretation,
    db: Session | None = None,
) -> PendingInterpretation:
    if not isinstance(interpretation.domain_route, dict) or not interpretation.domain_route:
        interpretation.domain_route = resolve_pending_domain_route(interpretation, db=db)
    return interpretation
