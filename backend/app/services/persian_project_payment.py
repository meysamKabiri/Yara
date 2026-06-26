import re
from dataclasses import dataclass

from app.services.persian_money_engine import normalize_text, parse_persian_money


@dataclass(frozen=True)
class IncomingProjectPayment:
    """Legacy pre-confirmation hint for payer extraction only."""

    payer_name: str
    amount: int | None


@dataclass(frozen=True)
class PurchasePayment:
    """Legacy pre-confirmation hint for vendor extraction only."""

    vendor_name: str | None
    amount: int | None


def detect_incoming_project_payment(text: str) -> IncomingProjectPayment | None:
    """Return an entity/amount hint; do not decide final direction or payment behavior."""
    normalized = normalize_text(text)
    if not _is_incoming_project_payment(normalized):
        return None
    payer_name = _payer_before_amount(normalized)
    if payer_name is None:
        return None
    return IncomingProjectPayment(
        payer_name=payer_name,
        amount=parse_persian_money(text),
    )


def detect_purchase_payment(text: str) -> PurchasePayment | None:
    """Return an entity/amount hint; do not decide final action, direction, or payment method."""
    normalized = normalize_text(text)
    if not _has_purchase_meaning(normalized):
        return None
    return PurchasePayment(
        vendor_name=_vendor_after_from(normalized),
        amount=parse_persian_money(text),
    )


def _is_incoming_project_payment(normalized: str) -> bool:
    direct_phrases = [
        "به حساب پروژه واریز کرد",
        "به حساب پروژه ریخت",
        "پول داد به پروژه",
        "برای پروژه واریز کرد",
        "gereftam baraye proje",
        "gereftam baraye project",
    ]
    if any(phrase in normalized for phrase in direct_phrases):
        return True
    if "واریز کرد" in normalized and "پروژه" in normalized and "حساب" in normalized:
        return True
    if "گرفتم" in normalized and "پروژه" in normalized:
        return True
    if "gereftam" in normalized and ("proje" in normalized or "project" in normalized):
        return True
    if "پول داد" in normalized and "پروژه" in normalized and "دادم" not in normalized:
        return True
    return False


def _payer_before_amount(normalized: str) -> str | None:
    match = re.match(
        r"^(?P<name>.+?)\s+\d+(?:\.\d+)?\s*(?:هزار|میلیون|میلیارد)?(?:\s|$)",
        normalized,
    )
    if match is None:
        return None
    name = match.group("name").strip(" ،,")
    name = re.sub(r"^(از|az|طرف|taraf)\s+", "", name, flags=re.IGNORECASE).strip()
    return name or None


def _has_purchase_meaning(normalized: str) -> bool:
    phrases = [
        "خریدم",
        "خرید کردم",
        "خریداری شد",
        "خریداری",
        "فاکتور گرفتم",
        "خرید نسیه",
        "فاکتور",
        "kharidam",
        "kharid kardam",
    ]
    if any(phrase in normalized for phrase in phrases):
        return True
    return (
        "پرداخت کردم" in normalized and "خرید" in normalized
    ) or (
        "پرداخت شد" in normalized and "خرید" in normalized
    ) or (
        "pardakht kardam" in normalized and "kharid" in normalized
    )


def _vendor_after_from(normalized: str) -> str | None:
    match = re.search(
        r"(?:^|\s)(?:از|az)\s+(?P<name>.+?)\s+\d+(?:\.\d+)?\s*(?:هزار|میلیون|میلیارد|thousand|million|billion)?(?:\s|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        match = re.search(
            r"(?:^|\s)(?:از|az)\s+(?P<name>.+?)\s+(?:خرید|خریدم|فاکتور|kharid|kharidam)",
            normalized,
            flags=re.IGNORECASE,
        )
    if match is None:
        return None
    name = match.group("name").strip(" ،,")
    return name or None
