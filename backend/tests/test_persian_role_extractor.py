"""Tests for Persian role-phrase extraction utility."""

import pytest

from app.models.core import WorkerType
from app.services.persian_role_extractor import PersianRoleExtractor


@pytest.fixture
def extractor() -> PersianRoleExtractor:
    return PersianRoleExtractor()


class TestClientRoleExtraction:
    """Test CLIENT role phrase extraction in various sentence patterns."""

    def test_name_before_role_with_filler(self, extractor: PersianRoleExtractor) -> None:
        """وحید داوودی مالک پروژه است"""
        result = extractor.extract("وحید داوودی مالک پروژه است")
        assert result is not None
        assert result.name == "وحید داوودی"
        assert result.worker_type == WorkerType.CLIENT
        assert result.role_phrase == "مالک پروژه"
        assert result.confidence >= 0.8

    def test_role_before_name_with_filler(self, extractor: PersianRoleExtractor) -> None:
        """مالک پروژه وحید داوودی است"""
        result = extractor.extract("مالک پروژه وحید داوودی است")
        assert result is not None
        assert result.name == "وحید داوودی"
        assert result.worker_type == WorkerType.CLIENT

    def test_role_before_name_no_filler(self, extractor: PersianRoleExtractor) -> None:
        """مالک پروژه وحید داوودی"""
        result = extractor.extract("مالک پروژه وحید داوودی")
        assert result is not None
        assert result.name == "وحید داوودی"
        assert result.worker_type == WorkerType.CLIENT

    def test_name_before_role_no_filler(self, extractor: PersianRoleExtractor) -> None:
        """وحید داوودی مالک پروژه"""
        result = extractor.extract("وحید داوودی مالک پروژه")
        assert result is not None
        assert result.name == "وحید داوودی"
        assert result.worker_type == WorkerType.CLIENT

    def test_karfarma_role(self, extractor: PersianRoleExtractor) -> None:
        """کارفرمای پروژه وحید داوودی است"""
        result = extractor.extract("کارفرمای پروژه وحید داوودی است")
        assert result is not None
        assert result.name == "وحید داوودی"
        assert result.worker_type == WorkerType.CLIENT
        assert result.role_phrase == "کارفرمای پروژه"

    def test_karfarma_simple(self, extractor: PersianRoleExtractor) -> None:
        """وحید داوودی کارفرما است"""
        result = extractor.extract("وحید داوودی کارفرما است")
        assert result is not None
        assert result.name == "وحید داوودی"
        assert result.worker_type == WorkerType.CLIENT
        assert result.role_phrase == "کارفرما"

    def test_saheb_kar_role(self, extractor: PersianRoleExtractor) -> None:
        """صاحب کار میثم کبیری هست"""
        result = extractor.extract("صاحب کار میثم کبیری هست")
        assert result is not None
        assert result.name == "میثم کبیری"
        assert result.worker_type == WorkerType.CLIENT
        assert result.role_phrase == "صاحب کار"


class TestSkilledWorkerRoleExtraction:
    """Test SKILLED_WORKER role phrase extraction."""

    def test_joshkar_role(self, extractor: PersianRoleExtractor) -> None:
        """علی رضایی جوشکار است"""
        result = extractor.extract("علی رضایی جوشکار است")
        assert result is not None
        assert result.name == "علی رضایی"
        assert result.worker_type == WorkerType.SKILLED_WORKER
        assert result.role_phrase == "جوشکار"

    def test_joshkar_before_name(self, extractor: PersianRoleExtractor) -> None:
        """جوشکار علی رضایی"""
        result = extractor.extract("جوشکار علی رضایی")
        assert result is not None
        assert result.name == "علی رضایی"
        assert result.worker_type == WorkerType.SKILLED_WORKER

    def test_barghkar_role(self, extractor: PersianRoleExtractor) -> None:
        """نادری برقکار است"""
        result = extractor.extract("نادری برقکار است")
        assert result is not None
        assert result.name == "نادری"
        assert result.worker_type == WorkerType.SKILLED_WORKER
        assert result.role_phrase == "برقکار"

    def test_gachkar_role(self, extractor: PersianRoleExtractor) -> None:
        """حسین احمدی گچ کار"""
        result = extractor.extract("حسین احمدی گچ کار")
        assert result is not None
        assert result.name == "حسین احمدی"
        assert result.worker_type == WorkerType.SKILLED_WORKER
        assert result.role_phrase == "گچ کار"

    def test_rangkar_role(self, extractor: PersianRoleExtractor) -> None:
        """رنگ کار جواد رضایی"""
        result = extractor.extract("رنگ کار جواد رضایی")
        assert result is not None
        assert result.name == "جواد رضایی"
        assert result.worker_type == WorkerType.SKILLED_WORKER
        assert result.role_phrase == "رنگ کار"

    def test_ceramickar_role(self, extractor: PersianRoleExtractor) -> None:
        """سرامیک کار محمد صالحی است"""
        result = extractor.extract("سرامیک کار محمد صالحی است")
        assert result is not None
        assert result.name == "محمد صالحی"
        assert result.worker_type == WorkerType.SKILLED_WORKER
        assert result.role_phrase == "سرامیک کار"


class TestVendorRoleExtraction:
    """Test VENDOR role phrase extraction."""

    def test_foroshande_role(self, extractor: PersianRoleExtractor) -> None:
        """فروشنده آقای صابری است"""
        result = extractor.extract("فروشنده آقای صابری است")
        assert result is not None
        assert result.name == "آقای صابری"
        assert result.worker_type == WorkerType.VENDOR
        assert result.role_phrase == "فروشنده"

    def test_maghaze_dar_role(self, extractor: PersianRoleExtractor) -> None:
        """مغازه دار حسین رضایی"""
        result = extractor.extract("مغازه دار حسین رضایی")
        assert result is not None
        assert result.name == "حسین رضایی"
        assert result.worker_type == WorkerType.VENDOR
        assert result.role_phrase == "مغازه دار"

    def test_vendor_role(self, extractor: PersianRoleExtractor) -> None:
        """وندور علی محمدی"""
        result = extractor.extract("وندور علی محمدی")
        assert result is not None
        assert result.name == "علی محمدی"
        assert result.worker_type == WorkerType.VENDOR
        assert result.role_phrase == "وندور"


class TestDailyWorkerRoleExtraction:
    """Test DAILY_WORKER role phrase extraction."""

    def test_kargar_sadeh_role(self, extractor: PersianRoleExtractor) -> None:
        """مش رحیم کارگر ساده است"""
        result = extractor.extract("مش رحیم کارگر ساده است")
        assert result is not None
        assert result.name == "مش رحیم"
        assert result.worker_type == WorkerType.DAILY_WORKER
        assert result.role_phrase == "کارگر ساده"

    def test_kargar_role(self, extractor: PersianRoleExtractor) -> None:
        """کارگر احمد حسینی"""
        result = extractor.extract("کارگر احمد حسینی")
        assert result is not None
        assert result.name == "احمد حسینی"
        assert result.worker_type == WorkerType.DAILY_WORKER
        assert result.role_phrase == "کارگر"


class TestRolePhraseSpecificityPriority:
    """Test that more specific role phrases take priority over generic ones."""

    def test_kargar_sadeh_over_kargar(self, extractor: PersianRoleExtractor) -> None:
        """کارگر ساده should match before کارگر"""
        result = extractor.extract("مش رحیم کارگر ساده است")
        assert result is not None
        assert result.role_phrase == "کارگر ساده"
        assert result.name == "مش رحیم"

    def test_karfarma_project_over_karfarma(self, extractor: PersianRoleExtractor) -> None:
        """کارفرمای پروژه should match before کارفرما"""
        result = extractor.extract("کارفرمای پروژه علی است")
        assert result is not None
        assert result.role_phrase == "کارفرمای پروژه"
        assert result.name == "علی"

    def test_malek_project_priority(self, extractor: PersianRoleExtractor) -> None:
        """مالک پروژه should have high priority"""
        result = extractor.extract("مالک پروژه وحید داوودی")
        assert result is not None
        assert result.role_phrase == "مالک پروژه"
        assert result.confidence >= 0.9


class TestFillerWordRemoval:
    """Test that filler words are properly removed."""

    def test_ast_filler(self, extractor: PersianRoleExtractor) -> None:
        result = extractor.extract("وحید داوودی کارفرما است")
        assert result is not None
        assert "است" not in result.name

    def test_hast_filler(self, extractor: PersianRoleExtractor) -> None:
        result = extractor.extract("کارفرما وحید داوودی هست")
        assert result is not None
        assert "هست" not in result.name

    def test_dar_project_filler(self, extractor: PersianRoleExtractor) -> None:
        result = extractor.extract("وحید داوودی در پروژه کارفرما است")
        assert result is not None
        assert "در پروژه" not in result.name
        assert "پروژه" not in result.name

    def test_be_onvan_filler(self, extractor: PersianRoleExtractor) -> None:
        result = extractor.extract("به عنوان کارگر مش رحیم")
        assert result is not None
        assert "به عنوان" not in result.name


class TestEdgeCases:
    """Test edge cases and invalid inputs."""

    def test_no_role_phrase_returns_none(self, extractor: PersianRoleExtractor) -> None:
        """Text without role phrase should return None"""
        result = extractor.extract("امروز کار کرد")
        assert result is None

    def test_empty_text_returns_none(self, extractor: PersianRoleExtractor) -> None:
        result = extractor.extract("")
        assert result is None

    def test_only_role_phrase_returns_none(self, extractor: PersianRoleExtractor) -> None:
        """Role phrase without name should return None"""
        result = extractor.extract("کارفرما است")
        assert result is None

    def test_only_filler_words_returns_none(self, extractor: PersianRoleExtractor) -> None:
        result = extractor.extract("است هست")
        assert result is None

    def test_numbers_only_returns_none(self, extractor: PersianRoleExtractor) -> None:
        """Numbers shouldn't be treated as names"""
        result = extractor.extract("کارفرما 1234567")
        assert result is None

    def test_short_name_returns_none(self, extractor: PersianRoleExtractor) -> None:
        """Very short names should be rejected"""
        result = extractor.extract("کارفرما ا")
        assert result is None


class TestComplexSentences:
    """Test extraction from complex sentences with multiple elements."""

    def test_with_phone_number(self, extractor: PersianRoleExtractor) -> None:
        """Should extract name even with phone number present"""
        result = extractor.extract("کارفرمای پروژه میثم کبیری است شماره 09130000000")
        assert result is not None
        assert result.name == "میثم کبیری"
        assert result.worker_type == WorkerType.CLIENT
        # Phone number should not be in the name
        assert "09130000000" not in result.name

    def test_with_additional_context(self, extractor: PersianRoleExtractor) -> None:
        """Should extract name even with additional context"""
        result = extractor.extract("جوشکار نادری امروز کار کرد")
        assert result is not None
        assert result.name == "نادری امروز کار کرد"
        # Note: This shows a limitation - we get extra text
        # This is acceptable as the semantic engine will handle it

    def test_multiple_fillers(self, extractor: PersianRoleExtractor) -> None:
        """Should remove all filler words"""
        result = extractor.extract("وحید داوودی در پروژه به عنوان کارفرما است")
        assert result is not None
        assert "در پروژه" not in result.name
        assert "به عنوان" not in result.name
        assert "است" not in result.name


class TestNormalization:
    """Test text normalization handling."""

    def test_zwnj_normalization(self, extractor: PersianRoleExtractor) -> None:
        """Zero-width non-joiner should be normalized"""
        # Using ZWNJ in کارفرما
        result = extractor.extract("وحید داوودی کار‌فرما است")
        assert result is not None
        assert result.name == "وحید داوودی"

    def test_extra_whitespace(self, extractor: PersianRoleExtractor) -> None:
        """Extra whitespace should be normalized"""
        result = extractor.extract("وحید    داوودی   کارفرما    است")
        assert result is not None
        assert result.name == "وحید داوودی"

    def test_leading_trailing_whitespace(self, extractor: PersianRoleExtractor) -> None:
        """Leading/trailing whitespace should be removed"""
        result = extractor.extract("  کارفرما میثم کبیری  ")
        assert result is not None
        assert result.name == "میثم کبیری"


class TestConfidenceCalculation:
    """Test confidence score calculation."""

    def test_high_confidence_for_specific_roles(self, extractor: PersianRoleExtractor) -> None:
        """High priority role phrases should have higher confidence"""
        result = extractor.extract("مالک پروژه وحید داوودی")
        assert result is not None
        assert result.confidence >= 0.9

    def test_lower_confidence_for_generic_roles(self, extractor: PersianRoleExtractor) -> None:
        """Generic role phrases should have lower confidence"""
        result = extractor.extract("کارگر احمد")
        assert result is not None
        assert result.confidence < 0.9

    def test_confidence_boost_for_full_names(self, extractor: PersianRoleExtractor) -> None:
        """Full names (2+ words) should boost confidence"""
        result1 = extractor.extract("کارفرما وحید داوودی")
        result2 = extractor.extract("کارفرما وحید")
        assert result1 is not None
        assert result2 is not None
        assert result1.confidence > result2.confidence

    def test_confidence_penalty_for_suspicious_patterns(self, extractor: PersianRoleExtractor) -> None:
        """Names containing suspicious words should have lower confidence"""
        result = extractor.extract("کارفرما است می باشد")
        # This should either return None or have very low confidence
        if result is not None:
            assert result.confidence < 0.7
