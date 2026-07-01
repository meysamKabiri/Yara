from app.core.domain_fallback_policy import (
    DEFAULT_FALLBACK,
    is_strong_setup_signal,
    is_fallback_domain,
    resolve_fallback,
)
from app.services.domain_router_service import DomainRouterService
from app.services.llm_v2_interpreter import LLMv2Interpreter, _wrap_bare_entity


def test_default_fallback_domain_is_note() -> None:
    assert DEFAULT_FALLBACK == "NOTE"
    assert is_fallback_domain("NOTE")
    assert is_fallback_domain("note")
    assert not is_fallback_domain("SETUP")


def test_unknown_input_resolves_to_note() -> None:
    assert resolve_fallback(context={"raw_text": "این را بعدا بررسی کن"}) == "NOTE"
    route = DomainRouterService().route("این را بعدا بررسی کن")
    assert route["domain"] == "NOTE"


def test_weak_setup_signal_resolves_to_note() -> None:
    context = {"raw_text": "علی", "interpretation": {"entities": [{"name": "علی"}]}}
    assert not is_strong_setup_signal(context)
    assert resolve_fallback(context=context) == "NOTE"


def test_strong_setup_signal_resolves_to_setup() -> None:
    assert is_strong_setup_signal({"raw_text": "علی به پروژه اضافه شد"})
    assert resolve_fallback(context={"raw_text": "علی به پروژه اضافه شد"}) == "SETUP"
    assert resolve_fallback(
        context={
            "entities": [
                {
                    "name": "علی",
                    "field_updates": {"phone": "09123456789"},
                }
            ]
        }
    ) == "SETUP"


def test_llm_failure_resolves_to_note() -> None:
    result = LLMv2Interpreter()._fallback("علی به پروژه اضافه شد", "test failure")
    assert result["intent"] == "NOTE"
    assert result["action"] == "NOTE"
    assert result["_llm_v2_failed"] is True


def test_weak_bare_entity_does_not_promote_to_setup() -> None:
    result = _wrap_bare_entity({"name": "علی", "kind": "PERSON"}, "علی")
    assert result["intent"] == "NOTE"
    assert result["action"] == "NOTE"
