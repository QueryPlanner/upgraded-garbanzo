"""Tests for Telegram model catalog and resolution."""

import pytest

from agent.telegram.model_settings import (
    active_provider_for_session_state,
    default_root_model,
    flat_menu_model_count,
    format_flat_model_menu,
    infer_provider_from_model_id,
    resolve_flat_menu_index,
    resolve_model_argument,
    resolve_model_freeform,
)
from agent.telegram_prefs import (
    TELEGRAM_SESSION_LITELLM_MODEL_KEY,
    TELEGRAM_SESSION_PROVIDER_KEY,
)


def test_flat_menu_count_matches_entries() -> None:
    assert flat_menu_model_count() == 6


def test_format_flat_model_menu_includes_providers() -> None:
    text = format_flat_model_menu()
    assert "1." in text
    assert "*openai*" in text
    assert "*openrouter*" in text
    assert "openai/glm-4.7" in text


def test_resolve_flat_menu_index() -> None:
    full, err = resolve_flat_menu_index(1)
    assert err is None
    assert full == "openai/glm-4.7"

    full2, err2 = resolve_flat_menu_index(3)
    assert err2 is None
    assert full2 == "openrouter/z-ai/glm-4.7"

    full_bad, err_bad = resolve_flat_menu_index(99)
    assert full_bad is None
    assert err_bad is not None


def test_infer_provider_from_model_id() -> None:
    assert infer_provider_from_model_id("openrouter/x") == "openrouter"
    assert infer_provider_from_model_id("openai/x") == "openai"
    assert infer_provider_from_model_id("gemini-pro") is None


@pytest.mark.parametrize(
    ("provider", "arg", "expected_id"),
    [
        ("openai", "1", "openai/glm-4.7"),
        ("openai", "2", "openai/glm-5"),
        ("openai", "glm-5", "openai/glm-5"),
        ("openrouter", "1", "openrouter/z-ai/glm-4.7"),
        ("openrouter", "z-ai/glm-4.7", "openrouter/z-ai/glm-4.7"),
        ("openrouter", "minimax/minimax-m2.7", "openrouter/minimax/minimax-m2.7"),
    ],
)
def test_resolve_model_argument_ok(provider: str, arg: str, expected_id: str) -> None:
    full, err = resolve_model_argument(provider, arg)  # type: ignore[arg-type]
    assert err is None
    assert full == expected_id


def test_resolve_openrouter_full_id_matches_list_entry() -> None:
    full, err = resolve_model_argument("openrouter", "openrouter/z-ai/glm-5")
    assert err is None
    assert full == "openrouter/z-ai/glm-5"


def test_resolve_model_argument_errors() -> None:
    full, err = resolve_model_argument("openai", "")
    assert full is None
    assert err is not None

    full2, err2 = resolve_model_argument("openai", "99")
    assert full2 is None
    assert err2 is not None

    full3, err3 = resolve_model_argument("openai", "unknown-model")
    assert full3 is None
    assert err3 is not None


def test_resolve_model_freeform_prefers_openai_on_ambiguous_short_name() -> None:
    """Same short suffix can exist on both sides; openai is tried first."""
    full, err = resolve_model_freeform("glm-5")
    assert err is None
    assert full == "openai/glm-5"


def test_resolve_model_freeform_unknown() -> None:
    full, err = resolve_model_freeform("totally-unknown-xyz")
    assert full is None
    assert "Unknown model" in (err or "")


def test_resolve_model_freeform_whitespace_only() -> None:
    full, err = resolve_model_freeform("   ")
    assert full is None
    assert "number from /model" in (err or "")


def test_active_provider_for_session_state(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        active_provider_for_session_state(
            {TELEGRAM_SESSION_PROVIDER_KEY: "openai"},
        )
        == "openai"
    )
    assert (
        active_provider_for_session_state(
            {TELEGRAM_SESSION_PROVIDER_KEY: "openrouter"},
        )
        == "openrouter"
    )
    assert (
        active_provider_for_session_state(
            {
                TELEGRAM_SESSION_LITELLM_MODEL_KEY: "openrouter/z-ai/glm-5",
            },
        )
        == "openrouter"
    )
    monkeypatch.delenv("ROOT_AGENT_MODEL", raising=False)
    assert active_provider_for_session_state({}) == "openrouter"

    monkeypatch.setenv("ROOT_AGENT_MODEL", "openai/gpt-4o-mini")
    assert active_provider_for_session_state({}) == "openai"


def test_default_root_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROOT_AGENT_MODEL", raising=False)
    assert default_root_model() == "gemini-2.5-flash"
    monkeypatch.setenv("ROOT_AGENT_MODEL", "openai/x")
    assert default_root_model() == "openai/x"
