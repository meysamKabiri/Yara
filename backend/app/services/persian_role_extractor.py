"""
Generic Persian role-phrase extraction utility.

Detects role phrases anywhere in a sentence, strips them along with filler words,
and extracts the entity name and worker type.

Example:
    "وحید داوودی مالک پروژه است" -> name="وحید داوودی", type="CLIENT"
    "مالک پروژه وحید داوودی است" -> name="وحید داوودی", type="CLIENT"
    "جوشکار علی رضایی" -> name="علی رضایی", type="SKILLED_WORKER"
"""

import re
from dataclasses import dataclass

from app.models.core import WorkerType
from app.services.persian_money_engine import normalize_text


@dataclass(frozen=True)
class RolePhrase:
    """A Persian role phrase with its associated worker type."""

    phrase: str
    worker_type: WorkerType
    priority: int = 0  # Higher priority phrases matched first


@dataclass(frozen=True)
class ExtractedRole:
    """Result of role extraction from Persian text."""

    name: str
    worker_type: WorkerType
    role_phrase: str  # The matched role phrase
    confidence: float


# Role phrases ordered by specificity (most specific first)
ROLE_PHRASES: list[RolePhrase] = [
    # Client/Owner roles
    RolePhrase("مالک پروژه", WorkerType.CLIENT, priority=10),
    RolePhrase("کارفرمای پروژه", WorkerType.CLIENT, priority=10),
    RolePhrase("صاحب کار", WorkerType.CLIENT, priority=9),
    RolePhrase("کارفرما", WorkerType.CLIENT, priority=8),
    RolePhrase("کار فرما", WorkerType.CLIENT, priority=8),  # Handle separated form
    # Skilled worker roles (trade-specific)
    RolePhrase("جوشکار", WorkerType.SKILLED_WORKER, priority=7),
    RolePhrase("برقکار", WorkerType.SKILLED_WORKER, priority=7),
    RolePhrase("گچ کار", WorkerType.SKILLED_WORKER, priority=7),
    RolePhrase("رنگ کار", WorkerType.SKILLED_WORKER, priority=7),
    RolePhrase("سرامیک کار", WorkerType.SKILLED_WORKER, priority=7),
    # Vendor roles
    RolePhrase("فروشنده", WorkerType.VENDOR, priority=6),
    RolePhrase("مغازه دار", WorkerType.VENDOR, priority=6),
    RolePhrase("وندور", WorkerType.VENDOR, priority=6),
    # Generic worker roles (lower priority)
    RolePhrase("کارگر ساده", WorkerType.DAILY_WORKER, priority=5),
    RolePhrase("کارگر", WorkerType.DAILY_WORKER, priority=4),
]

# Filler words to remove from extracted names
FILLER_WORDS: list[str] = [
    "است",
    "هست",
    "می باشد",
    "می‌باشد",
    "در پروژه",
    "به عنوان",
    "پروژه",
    "ما",
    "این",
    "شماره",
    "شماره تماس",
]


class PersianRoleExtractor:
    """
    DEPRECATED: Will be removed after full LLM migration.
    Kept for backward compatibility only.

    Extract entity names and roles from Persian setup sentences.
    """

    def __init__(self) -> None:
        self.role_phrases = sorted(ROLE_PHRASES, key=lambda r: r.priority, reverse=True)
        self.filler_words = FILLER_WORDS

    def extract(self, text: str) -> ExtractedRole | None:
        """
        Extract entity name and role from Persian text.

        Returns None if no role phrase is found.
        """
        normalized = self._normalize(text)

        # Try each role phrase by priority
        for role_phrase in self.role_phrases:
            if role_phrase.phrase in normalized:
                name = self._extract_name(normalized, role_phrase.phrase)
                if name:
                    return ExtractedRole(
                        name=name,
                        worker_type=role_phrase.worker_type,
                        role_phrase=role_phrase.phrase,
                        confidence=self._calculate_confidence(normalized, name, role_phrase),
                    )

        return None

    def _extract_name(self, normalized_text: str, role_phrase: str) -> str | None:
        """
        Remove role phrase and filler words, extract remaining text as name.

        Handles both patterns:
        - "name + role_phrase + filler"
        - "role_phrase + name + filler"
        """
        # Remove the role phrase
        text_without_role = normalized_text.replace(role_phrase, " ")

        # Remove phone numbers (09xxxxxxxxx pattern) BEFORE removing filler words
        text_without_role = re.sub(r"0\d{10}", " ", text_without_role)
        
        # Remove other long digit sequences (likely account numbers, etc)
        text_without_role = re.sub(r"\d{8,}", " ", text_without_role)
        
        # Remove filler words (using word boundaries to avoid partial matches)
        for filler in self.filler_words:
            # Use regex with word boundaries (\b) for single-word fillers
            # For multi-word fillers, use exact match with spaces
            if " " in filler:
                text_without_role = text_without_role.replace(filler, " ")
            else:
                # Match as whole word only
                pattern = r"\b" + re.escape(filler) + r"\b"
                text_without_role = re.sub(pattern, " ", text_without_role)

        # Clean up whitespace
        name = re.sub(r"\s+", " ", text_without_role).strip()

        # Filter out empty or too-short names
        if not name or len(name) < 2:
            return None

        # Filter out names that are just numbers or punctuation
        if re.match(r"^[\d\s\.\-]+$", name):
            return None

        return name

    def _calculate_confidence(
        self,
        normalized_text: str,
        name: str,
        role_phrase: RolePhrase,
    ) -> float:
        """Calculate extraction confidence based on various factors."""
        confidence = 0.8  # Base confidence

        # Higher confidence for higher priority role phrases
        if role_phrase.priority >= 9:
            confidence += 0.1

        # Lower confidence if name contains suspicious patterns
        if any(word in name for word in ["است", "هست", "می"]):
            confidence -= 0.2

        # Higher confidence if name has typical Persian name structure
        if len(name.split()) >= 2:
            confidence += 0.1

        return max(0.3, min(1.0, confidence))

    def _normalize(self, text: str) -> str:
        """Normalize Persian text for matching."""
        return normalize_text(text).replace("\u200c", " ").strip()
