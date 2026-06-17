import logging
import re

logger = logging.getLogger(__name__)

PERSIAN_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
UNIT_MULTIPLIERS = {
    "هزار": 1_000,
    "thousand": 1_000,
    "میلیون": 1_000_000,
    "million": 1_000_000,
    "میلیونش را": 1_000_000,
    "میلیونش": 1_000_000,
    "میلیارد": 1_000_000_000,
    "billion": 1_000_000_000,
}
PERSIAN_NUMBER_WORDS = {
    "یک": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "شش": 6,
    "هفت": 7,
    "هشت": 8,
    "نه": 9,
    "ده": 10,
    "صد": 100,
}
UNIT_PATTERN = r"هزار|thousand|میلیونش را|میلیونش|میلیون|million|میلیارد|billion"
NUMBER_UNIT_PATTERN = re.compile(rf"(?<!\w)(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})?(?!\w)")
PERSIAN_HALF_PATTERN = re.compile(
    rf"({'|'.join(PERSIAN_NUMBER_WORDS)})\s+و\s+نیم\s*({UNIT_PATTERN})"
)
NUMERIC_HALF_PATTERN = re.compile(rf"(\d+)\s+و\s+نیم\s*({UNIT_PATTERN})")
PERSIAN_WORD_UNIT_PATTERN = re.compile(rf"({'|'.join(PERSIAN_NUMBER_WORDS)})\s*({UNIT_PATTERN})")


def normalize_text(text: str) -> str:
    normalized = text.translate(PERSIAN_DIGIT_TRANSLATION).lower()
    normalized = normalized.replace("ميليون", "میلیون")
    normalized = normalized.replace("ملیون", "میلیون")
    normalized = normalized.replace("ملین", "میلیون")
    normalized = normalized.replace("billion", "میلیارد")
    normalized = normalized.replace("thousand", "هزار")
    normalized = normalized.replace("million", "میلیون")
    normalized = normalized.replace("میلیونشا", "میلیونش را")
    normalized = normalized.replace("میلیاردش", "میلیارد")
    normalized = normalized.replace("هزارش", "هزار")
    normalized = normalized.replace(",", "")
    normalized = re.sub(r"(?<=\d)/(?=\d)", ".", normalized)
    normalized = re.sub(r"[؛،:;!?؟()\[\]{}\-ـ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def parse_persian_money(text: str) -> int | None:
    normalized = normalize_text(text)
    parsed_value = _parse_normalized_money(normalized)
    logger.info(
        "parsed Persian money amount",
        extra={
            "amount_text": text,
            "normalized_amount_text": normalized,
            "parsed_amount": parsed_value,
        },
    )
    if parsed_value is not None and (parsed_value < 1000 or parsed_value > 1_000_000_000_000):
        logger.warning(
            "suspicious parsed Persian money amount",
            extra={
                "amount_text": text,
                "normalized_amount_text": normalized,
                "parsed_amount": parsed_value,
            },
        )
    return parsed_value


def _parse_normalized_money(text: str) -> int | None:
    half_match = PERSIAN_HALF_PATTERN.search(text)
    if half_match is not None:
        number = PERSIAN_NUMBER_WORDS[half_match.group(1)] + 0.5
        return int(number * UNIT_MULTIPLIERS[half_match.group(2)])

    numeric_half_match = NUMERIC_HALF_PATTERN.search(text)
    if numeric_half_match is not None:
        number = int(numeric_half_match.group(1)) + 0.5
        return int(number * UNIT_MULTIPLIERS[numeric_half_match.group(2)])

    word_match = PERSIAN_WORD_UNIT_PATTERN.search(text)
    if word_match is not None:
        number = PERSIAN_NUMBER_WORDS[word_match.group(1)]
        return number * UNIT_MULTIPLIERS[word_match.group(2)]

    matches = list(NUMBER_UNIT_PATTERN.finditer(text))
    for match in matches:
        unit = match.group(2)
        if unit is not None:
            return int(float(match.group(1)) * UNIT_MULTIPLIERS[unit])

    if len(matches) == 1 and matches[0].group(2) is None:
        return int(float(matches[0].group(1)))
    return None
