# Agent Instructions

`PROJECT-PLAN.md` is the source of truth for Yara architecture and product behavior.

Before making any code change, every agent must:

1. Read `PROJECT-PLAN.md`.
2. Identify the affected domain: `TASK`, `SETUP`, `FINANCIAL`, or `NOTE`.
3. Check the requested change against domain boundaries, UX principles, data rules, domain priority, forbidden patterns, and change policy.
4. Respond with this exact validation block before editing files:

```text
PLAN COMPATIBILITY RESULT: COMPLIANT | NON-COMPLIANT
RULES IMPACTED:
- ...
RISK LEVEL: LOW | MEDIUM | HIGH
RECOMMENDED ACTION: proceed | modify | reject
```

Proceed only when the result is `COMPLIANT`.

If the result is `NON-COMPLIANT`, stop and suggest a plan-compatible alternative. If `PROJECT-PLAN.md` is unclear for the request, ask before coding.

Useful helper:

```bash
python3 scripts/plan_guard.py --request "describe the requested change"
```

The helper is advisory. The agent is still responsible for reading `PROJECT-PLAN.md` and applying judgment before editing.
