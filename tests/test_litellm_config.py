"""Tests for agent.litellm_config (LiteLLM kwargs from environment)."""

import pytest

from agent.litellm_config import build_litellm_kwargs


def test_openrouter_requires_key_or_proxy_credentials() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_litellm_kwargs(
            "openrouter/google/gemini-2.0-flash-001",
            environ={},
        )


def test_openrouter_via_openai_compatible_proxy_without_openrouter_key() -> None:
    kwargs = build_litellm_kwargs(
        "openrouter/z-ai/glm-4.7",
        environ={
            "OPENAI_API_KEY": "sk-proxy",
            "OPENAI_API_BASE": "http://localhost:4000/",
        },
    )
    assert kwargs["model"] == "openrouter/z-ai/glm-4.7"
    assert kwargs["api_key"] == "sk-proxy"
    assert kwargs["api_base"] == "http://localhost:4000"


def test_openrouter_openai_key_without_base_raises() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_BASE"):
        build_litellm_kwargs(
            "openrouter/z-ai/glm-4.7",
            environ={"OPENAI_API_KEY": "sk-only"},
        )


def test_openrouter_sets_api_key_and_optional_provider_order() -> None:
    env = {
        "OPENROUTER_API_KEY": "sk-or-test",
        "OPENROUTER_PROVIDER_ORDER": '["google-vertex"]',
    }
    kwargs = build_litellm_kwargs("openrouter/some/model", environ=env)
    assert kwargs["model"] == "openrouter/some/model"
    assert kwargs["api_key"] == "sk-or-test"
    assert kwargs["extra_body"] == {"provider": {"order": ["google-vertex"]}}


def test_openrouter_invalid_provider_order_json_skips_extra_body() -> None:
    env = {
        "OPENROUTER_API_KEY": "sk-or-test",
        "OPENROUTER_PROVIDER_ORDER": "not-json",
    }
    kwargs = build_litellm_kwargs("openrouter/some/model", environ=env)
    assert kwargs["api_key"] == "sk-or-test"
    assert "extra_body" not in kwargs


def test_google_model_uses_google_api_key() -> None:
    kwargs = build_litellm_kwargs(
        "google/gemini-2.0-flash-001",
        environ={"GOOGLE_API_KEY": "g-key"},
    )
    assert kwargs["api_key"] == "g-key"


def test_openai_compatible_base_and_key() -> None:
    kwargs = build_litellm_kwargs(
        "gpt-4o-mini",
        environ={
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_API_BASE": "http://localhost:4000/",
        },
    )
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["api_base"] == "http://localhost:4000"


def test_openai_base_url_alias() -> None:
    kwargs = build_litellm_kwargs(
        "gpt-4o-mini",
        environ={
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "http://127.0.0.1:4000",
        },
    )
    assert kwargs["api_base"] == "http://127.0.0.1:4000"


def test_openai_api_base_preferred_over_openai_base_url() -> None:
    kwargs = build_litellm_kwargs(
        "gpt-4o-mini",
        environ={
            "OPENAI_API_BASE": "http://a:1",
            "OPENAI_BASE_URL": "http://b:2",
        },
    )
    assert kwargs["api_base"] == "http://a:1"


def test_google_branch_ignores_openai_env() -> None:
    kwargs = build_litellm_kwargs(
        "google/gemini-2.0-flash-001",
        environ={
            "GOOGLE_API_KEY": "g-key",
            "OPENAI_API_KEY": "sk-x",
            "OPENAI_API_BASE": "http://localhost:4000",
        },
    )
    assert kwargs["api_key"] == "g-key"
    assert "api_base" not in kwargs
