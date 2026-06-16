import re
from decimal import Decimal, InvalidOperation

from app.models.core import (
    CounterpartyType,
    ExtractedEvent,
    ExtractedEventStatus,
    ExtractedEventType,
)

MONEY_IN_KEYWORDS = ("received", "paid me", "client paid", "گرفتم", "واریز")
MONEY_OUT_KEYWORDS = ("paid", "gave", "دادم", "پرداخت کردم")
PURCHASE_KEYWORDS = ("bought", "خریدم", "خرید")
AMOUNT_PATTERN = re.compile(r"(?<!\w)\d+(?:[,.]\d{3})*(?:\.\d+)?(?!\w)")


def extract_pending_events(text: str) -> list[ExtractedEvent]:
    event_type = _extract_event_type(text)
    amount = _extract_amount(text)

    if event_type is None:
        event_type = ExtractedEventType.NOTE

    return [
        ExtractedEvent(
            type=event_type,
            counterparty_type=CounterpartyType.UNKNOWN,
            amount=amount if event_type != ExtractedEventType.NOTE else None,
            description=text,
            confidence=Decimal("0.5000"),
            status=ExtractedEventStatus.PENDING,
        )
    ]


def _extract_event_type(text: str) -> ExtractedEventType | None:
    normalized_text = text.casefold()
    if _contains_keyword(normalized_text, MONEY_IN_KEYWORDS):
        return ExtractedEventType.MONEY_IN
    if _contains_keyword(normalized_text, PURCHASE_KEYWORDS):
        return ExtractedEventType.PURCHASE
    if _contains_keyword(normalized_text, MONEY_OUT_KEYWORDS):
        return ExtractedEventType.MONEY_OUT
    return None


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.casefold() in text for keyword in keywords)


def _extract_amount(text: str) -> Decimal | None:
    match = AMOUNT_PATTERN.search(text)
    if match is None:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None
