from app.services.persian_money_engine import normalize_text


QWEN_JSON_MODE_PREFIX = """/no_think
Return only valid JSON. Do not include reasoning, explanations, markdown, or thinking text."""

LLM_V2_SCHEMA = """Return compact minified JSON only.
Single-event schema:
{"intent":"SET_ROLE|SETUP|WORK|FINANCIAL|NOTE|DOCUMENT","action":"SET_ROLE|ADD_ENTITY|UPDATE_ENTITY|WORK_LOG|PAYMENT_IN|PAYMENT_OUT|PURCHASE_PAID|DEBT_CREATED|CHECK_PAYMENT|NOTE","matched_text":"exact source span","entities":[{"name":"string","kind":"PERSON|COMPANY|UNKNOWN","project_role":"CLIENT|DAILY_WORKER|SKILLED_WORKER|VENDOR|OTHER","role_detail":null,"phone":null,"account_number":null,"daily_rate":null,"notes":null,"field_updates":null}],"financial":{"amount":null,"direction":"IN|OUT|NONE","payment_method":null,"due_date_text":null},"work":{"quantity":null,"unit":null,"description":null},"note":{"text":null},"confidence":0.9,"ambiguity":false,"missing_fields":[],"reasoning_summary":"short"}"""

FINANCIAL_SCHEMA = """Return one compact JSON object with only these keys:
{"intent":"FINANCIAL","action":"PAYMENT_IN|PAYMENT_OUT|PURCHASE_PAID|DEBT_CREATED|CHECK_PAYMENT","entities":[{"name":"string","project_role":"CLIENT|VENDOR|OTHER"}],"financial":{"amount":number,"direction":"IN|OUT","payment_method":"CASH|BANK_TRANSFER|CHECK|OTHER|null"}}"""

COMMON_RULES = """Rules: preserve Persian names; amounts are تومان numbers (5 میلیون=5000000); use only listed enum values; no prose."""

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
    domain = detect_prompt_domain(raw_text)
    schema = FINANCIAL_SCHEMA if domain == "financial" else LLM_V2_SCHEMA
    prompt = "\n".join(
        part
        for part in [
            QWEN_JSON_MODE_PREFIX,
            "Extract from a Persian contractor note. Omit optional null fields.",
            schema,
            COMMON_RULES,
            _domain_rules(domain),
            f"Project ID: {project_id}",
            f"Note: {raw_text}",
        ]
        if part
    )
    return prompt, domain


def detect_prompt_domain(raw_text: str) -> str:
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
