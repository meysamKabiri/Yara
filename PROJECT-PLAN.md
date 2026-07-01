# YARA PROJECT PLAN

## 1. System Vision

AI-powered project execution system for managing construction/work projects through natural language input.

## 2. Core Domains

### TASK

- Execution actions (physical work)
- Always project-scoped

### SETUP

- Project structure changes
- Worker/member management
- Role assignment

### FINANCIAL

- Money flow
- Payments and costs

### NOTE

- Fallback only for unclear inputs

## TASK vs SETUP Boundary (CRITICAL)

### TASK

Only real-world physical execution:

- construction work
- manual operations
- field work

### SETUP

System-level or workflow-level changes:

- architecture changes
- CI/CD integration
- developer tooling
- backend/frontend system updates
- orchestration logic

### RULE

If it affects codebase behavior or system design → SETUP, NOT TASK

## 3. UX Principles

- All flows must go through modal confirmation
- Project context must never be lost
- No global task system

## 4. Data Rules

- `final_task_object` is the single source of truth
- Deterministic overrides > LLM output
- UI must never depend on raw LLM output

## 5. Domain Priority

TASK > FINANCIAL > SETUP > NOTE

## 6. Forbidden Patterns

- Global task system
- Hardcoded role lists
- SETUP fallback misuse
- Direct navigation to home after actions

## 7. Change Policy

All changes must:

1. Be checked against this plan
2. Not violate domain rules
3. Update this document if system behavior changes

## 8. Plan-Aware Change Guard

Before making any code change, Codex or another agent must load this file and compare the requested change against the rules above.

Every change request must receive this validation output before implementation:

### A. PLAN COMPATIBILITY RESULT

- `COMPLIANT` or `NON-COMPLIANT`

### B. RULES IMPACTED

- List every violated or uncertain rule
- Use `none` when no rule is violated

### C. RISK LEVEL

- `LOW`, `MEDIUM`, or `HIGH`

### D. RECOMMENDED ACTION

- `proceed`, `modify`, or `reject`

Implementation rules:

- If the change is `COMPLIANT`, proceed.
- If the change is `NON-COMPLIANT`, stop and suggest a plan-compatible fix.
- If this plan is unclear, ask before coding.
- No change may override this plan silently.
