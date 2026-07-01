#!/usr/bin/env python3
"""Plan-aware change guard for Yara agent workflows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "PROJECT-PLAN.md"


DOMAIN_KEYWORDS = {
    "TASK": (
        "task",
        "tasks",
        "assignment",
        "due date",
        "execution",
        "work",
        "physical",
        "کار",
        "وظیفه",
    ),
    "FINANCIAL": (
        "financial",
        "payment",
        "payments",
        "cost",
        "costs",
        "money",
        "invoice",
        "paid",
        "payable",
        "مالی",
        "پرداخت",
        "هزینه",
    ),
    "SETUP": (
        "setup",
        "worker",
        "workers",
        "member",
        "members",
        "role",
        "roles",
        "project structure",
        "کارگر",
        "عضو",
        "نقش",
    ),
    "NOTE": (
        "note",
        "notes",
        "unclear",
        "fallback",
        "raw note",
        "یادداشت",
        "نامشخص",
    ),
}


FORBIDDEN_CHECKS = (
    ("Global task system", ("global task", "all projects task", "cross-project task")),
    ("Hardcoded role lists", ("hardcoded role", "fixed role list", "static role list")),
    ("SETUP fallback misuse", ("setup fallback", "fallback to setup", "default to setup")),
    (
        "Direct navigation to home after actions",
        ("navigate home", "go home after", "redirect home", "redirect to home"),
    ),
    (
        "UI must never depend on raw LLM output",
        ("raw llm", "llm output directly", "display llm output"),
    ),
    (
        "All flows must go through modal confirmation",
        ("skip confirmation", "without confirmation", "no modal"),
    ),
    (
        "Project context must never be lost",
        ("drop project context", "without project context", "no project context"),
    ),
)


@dataclass(frozen=True)
class GuardResult:
    domains: list[str]
    compliance: str
    impacted_rules: list[str]
    risk_level: str
    recommended_action: str


def load_plan() -> str:
    if not PLAN_PATH.exists():
        raise FileNotFoundError(f"Missing required plan file: {PLAN_PATH}")
    return PLAN_PATH.read_text(encoding="utf-8")


def detect_domains(request: str) -> list[str]:
    text = request.casefold()
    matches: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword.casefold() in text for keyword in keywords):
            matches.append(domain)
    return matches or ["NOTE"]


def validate_request(request: str, plan_text: str) -> GuardResult:
    text = request.casefold()
    impacted = [
        rule for rule, needles in FORBIDDEN_CHECKS if any(needle in text for needle in needles)
    ]

    domains = detect_domains(request)
    if "TASK" in domains and "project" not in text and "پروژه" not in text:
        impacted.append("TASK changes must be project-scoped")

    compliance = "NON-COMPLIANT" if impacted else "COMPLIANT"
    if not impacted:
        risk_level = "LOW"
        recommended_action = "proceed"
    elif len(impacted) == 1:
        risk_level = "MEDIUM"
        recommended_action = "modify"
    else:
        risk_level = "HIGH"
        recommended_action = "reject"

    return GuardResult(
        domains=domains,
        compliance=compliance,
        impacted_rules=impacted,
        risk_level=risk_level,
        recommended_action=recommended_action,
    )


def format_result(result: GuardResult) -> str:
    rules = "\n".join(f"- {rule}" for rule in result.impacted_rules) or "- none"
    domains = ", ".join(result.domains)
    return "\n".join(
        (
            f"AFFECTED DOMAIN: {domains}",
            f"PLAN COMPATIBILITY RESULT: {result.compliance}",
            "RULES IMPACTED:",
            rules,
            f"RISK LEVEL: {result.risk_level}",
            f"RECOMMENDED ACTION: {result.recommended_action}",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Natural-language change request to validate.")
    args = parser.parse_args()

    plan_text = load_plan()
    result = validate_request(args.request, plan_text)
    print(format_result(result))
    return 1 if result.compliance == "NON-COMPLIANT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
