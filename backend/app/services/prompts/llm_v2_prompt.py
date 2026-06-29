import json

from app.services.input_normalizer import normalize_user_input
from app.services.llm_classification_contract import (
    ALLOWED_ACTIONS,
    ALLOWED_DOMAINS,
    ALLOWED_ENTITY_TYPES,
    ALLOWED_FINANCIAL_DIRECTIONS,
    ALLOWED_PROJECT_ROLES,
)
from app.services.persian_money_engine import normalize_text

QWEN_JSON_MODE_PREFIX = """/no_think
Return only valid JSON. Do not include reasoning, explanations, markdown, or thinking text."""

LLM_V2_SCHEMA = """Return compact minified JSON only.
Controlled classification schema:
{"domain":"SETUP|FINANCIAL|WORK|CONTACT|ACCOUNT|NOTE|OTHER","action":"CREATE_OR_UPDATE_PROFILE|UPDATE_PHONE|UPDATE_ACCOUNT|REGISTER_PAYMENT|REGISTER_INVOICE|REGISTER_WORK_LOG|ADD_NOTE|OTHER","entity_type":"PERSON|COMPANY|UNKNOWN","project_role":"CLIENT|VENDOR|DAILY_WORKER|SKILLED_WORKER|OTHER","selected_name":null,"role_detail":null,"financial_direction":"INCOMING|OUTGOING|NONE|UNKNOWN","amount":null,"phone":null,"account_number":null,"confidence":0.9}"""

FINANCIAL_SCHEMA = """Return one compact JSON object with only these keys:
{"intent":"FINANCIAL","action":"PAYMENT_IN|PAYMENT_OUT|PURCHASE_PAID|DEBT_CREATED|CHECK_PAYMENT","entities":[{"name":"string","project_role":"CLIENT|VENDOR|OTHER"}],"financial":{"amount":number,"direction":"IN|OUT","payment_method":"CASH|BANK_TRANSFER|CHECK|OTHER|null"}}"""

COMMON_RULES = """Rules:
- Use only listed enum values.
- You are NOT allowed to invent enum values.
- You are NOT allowed to invent person names.
- Prefer selected_name from name_candidates.
- Never include role words inside selected_name.
- If uncertain, return OTHER instead of guessing.
- Keep role_detail separate from selected_name.
- No prose."""
STRUCTURED_INPUT_RULES = """Input is normalized evidence JSON. raw_input is for reference only. Do not parse a raw sentence. Select names only from name_candidates unless no candidate exists. Classify domain/action from evidence, facts, and financials only."""

FINANCIAL_RULES = """Financial focus:
- خرید paid now => PURCHASE_PAID, OUT, VENDOR, CASH.
- نسیه/فاکتور/بدهی => DEBT_CREATED. چک => CHECK_PAYMENT.
- incoming client/project money => PAYMENT_IN, IN, CLIENT.
- amount + money movement (ریخت به حساب/واریز کرد/زد به حساب/از X گرفتم) => FINANCIAL, not SETUP.
- outgoing to unknown person => PAYMENT_OUT, OUT, OTHER.
- BANK_TRANSFER only for کارت/واریز/حساب/انتقال/بانکی."""

SETUP_RULES = """Setup/entity focus:
- Role-only statements use SET_ROLE + SET_ROLE.
- New person/company introduction uses SETUP + ADD_ENTITY.
- Phone/account/card/rate/note updates use SETUP + UPDATE_ENTITY.
- Put phone/account/daily_rate in both the entity field and field_updates."""

WORK_RULES = """Work focus:
- Labor, attendance, progress, meter/day/item quantities use WORK + WORK_LOG.
- Set work.quantity and work.unit when present."""

NOTE_RULES = """Note focus:
- Reminders or informational notes with no executable setup, work, or financial action use NOTE + NOTE."""


def build_llm_v2_prompt(raw_text: str, project_id: int) -> tuple[str, str]:
    structured_input = normalize_user_input(raw_text)
    domain = detect_prompt_domain(raw_text, structured_input)
    schema = LLM_V2_SCHEMA
    prompt = "\n".join(
        part
        for part in [
            QWEN_JSON_MODE_PREFIX,
            "Classify a normalized contractor input using the controlled classification contract.",
            schema,
            "Allowed domain values: " + ", ".join(sorted(ALLOWED_DOMAINS)),
            "Allowed action values: " + ", ".join(sorted(ALLOWED_ACTIONS)),
            "Allowed entity_type values: " + ", ".join(sorted(ALLOWED_ENTITY_TYPES)),
            "Allowed project_role values: " + ", ".join(sorted(ALLOWED_PROJECT_ROLES)),
            "Allowed financial_direction values: " + ", ".join(sorted(ALLOWED_FINANCIAL_DIRECTIONS)),
            COMMON_RULES,
            STRUCTURED_INPUT_RULES,
            _domain_rules(domain),
            f"Project ID: {project_id}",
            f"raw_input for reference only: {raw_text}",
            "Normalized input JSON:",
            json.dumps(structured_input, ensure_ascii=False, separators=(",", ":")),
        ]
        if part
    )
    return prompt, domain


def detect_prompt_domain(raw_text: str, structured_input: dict | None = None) -> str:
    structured_input = structured_input or normalize_user_input(raw_text)
    facts = structured_input.get("facts") or []
    financials = structured_input.get("financials") or {}
    if any(isinstance(fact, dict) and fact.get("type") == "AMOUNT" for fact in facts):
        return "setup"
    if isinstance(financials, dict) and financials.get("amount") is not None:
        return "financial"
    if any(isinstance(fact, dict) and fact.get("type") in {"PHONE", "ACCOUNT_NUMBER", "ROLE_TOKEN"} for fact in facts):
        return "setup"
    normalized = normalize_text(raw_text)
    if any(separator in normalized for separator in [".", "۔", "؛", "\n"]):
        return "multi"
    if _has_financial_signal(normalized):
        return "financial"
    if any(term in normalized for term in ["شماره", "حساب", "کارت", "موبایل", "تلفن", "دستمزد", "روزی", "کارفرما", "مالک", "فروشنده", "کارگر", "جوشکار"]):
        return "setup"
    if any(term in normalized for term in ["متر", "روز", "کار کرد", "کارکرد", "اومد", "آمد"]):
        return "work"
    return "note"


def _domain_rules(domain: str) -> str:
    if domain == "financial":
        return FINANCIAL_RULES
    if domain == "setup":
        return SETUP_RULES
    if domain == "work":
        return WORK_RULES
    if domain == "note":
        return NOTE_RULES
    return "\n".join([FINANCIAL_RULES, SETUP_RULES, WORK_RULES, NOTE_RULES])


def _has_financial_signal(normalized: str) -> bool:
    amount_signal = any(term in normalized for term in ["تومان", "تومن", "ریال", "هزار", "میلیون", "میلیارد"])
    verb_signal = any(
        term in normalized
        for term in [
            "خرید", "خریدم", "پرداخت", "دادم", "داد", "گرفتم", "واریز",
            "ریخت", "زد به حساب", "به حساب", "چک", "فاکتور", "بدهی", "نسیه",
        ]
    )
    return amount_signal and verb_signal


LLM_V2_PROMPT = "\n".join([LLM_V2_SCHEMA, COMMON_RULES, FINANCIAL_RULES, SETUP_RULES, WORK_RULES, NOTE_RULES])
