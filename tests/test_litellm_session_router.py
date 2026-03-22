"""Tests for Telegram LiteLLM routing wrapper."""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest

from agent.litellm_session_router import (
    CURRENT_TELEGRAM_LITELLM_MODEL,
    TelegramLitellmRouter,
    _litellm_for_model_name,
    _llm_request_aligned_to_backend,
)


@pytest.fixture
def default_llm() -> LiteLlm:
    return LiteLlm(model="gpt-4o-mini", api_key="sk-test")


class _FakeBackend:
    """Minimal backend with a ``model`` id (see LiteLlm)."""

    def __init__(self, model_id: str, parts: list[object]) -> None:
        self.model = model_id
        self._parts = parts
        self.calls: list[tuple[object, bool]] = []

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncIterator[object]:
        self.calls.append((llm_request, stream))
        for p in self._parts:
            yield p


class TestTelegramLitellmRouter:
    """Exercise routing and caching."""

    def test_wrapping_sets_model_field(self, default_llm: LiteLlm) -> None:
        router = TelegramLitellmRouter.wrapping(default_llm)
        assert router.model == default_llm.model
        assert router.default_llm is default_llm

    @pytest.mark.asyncio
    async def test_generate_delegates_to_effective_backend(
        self, default_llm: LiteLlm
    ) -> None:
        router = TelegramLitellmRouter.wrapping(default_llm)
        mock_resp = MagicMock()
        fake = _FakeBackend("openai/glm-5", [mock_resp])

        req = LlmRequest(model=default_llm.model, contents=[])
        with patch.object(router, "_effective_backend", return_value=fake):
            out = [x async for x in router.generate_content_async(req, stream=False)]

        assert out == [mock_resp]
        assert len(fake.calls) == 1
        sent_request, _stream = fake.calls[0]
        assert isinstance(sent_request, LlmRequest)
        assert sent_request.model == "openai/glm-5"

    @pytest.mark.asyncio
    async def test_generate_leaves_request_when_model_already_matches(
        self, default_llm: LiteLlm
    ) -> None:
        router = TelegramLitellmRouter.wrapping(default_llm)
        mock_resp = MagicMock()
        fake = _FakeBackend(default_llm.model, [mock_resp])
        req = LlmRequest(model=default_llm.model, contents=[])
        with patch.object(router, "_effective_backend", return_value=fake):
            await _consume(router.generate_content_async(req, stream=False))
        sent_request, _ = fake.calls[0]
        assert sent_request is req


async def _consume(gen: AsyncIterator[object]) -> None:
    async for _ in gen:
        pass


class TestLlmRequestAlignedToBackend:
    """``_llm_request_aligned_to_backend`` copies when ADK pins the root model."""

    def test_no_copy_when_request_model_none(self, default_llm: LiteLlm) -> None:
        req = LlmRequest(model=None, contents=[])
        out = _llm_request_aligned_to_backend(req, default_llm)
        assert out is req

    def test_no_copy_when_models_match(self, default_llm: LiteLlm) -> None:
        req = LlmRequest(model=default_llm.model, contents=[])
        out = _llm_request_aligned_to_backend(req, default_llm)
        assert out is req

    def test_copy_when_request_model_differs(self, default_llm: LiteLlm) -> None:
        other = LiteLlm(model="openai/glm-5", api_key="sk-test")
        req = LlmRequest(model=default_llm.model, contents=[])
        out = _llm_request_aligned_to_backend(req, other)
        assert out is not req
        assert out.model == "openai/glm-5"
        assert req.model == default_llm.model

    def test_effective_backend_uses_litellm_for_model_name(
        self, default_llm: LiteLlm, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_other = MagicMock(spec=LiteLlm)
        monkeypatch.setattr(
            "agent.litellm_session_router._litellm_for_model_name",
            lambda _m: fake_other,
        )
        router = TelegramLitellmRouter.wrapping(default_llm)
        token = CURRENT_TELEGRAM_LITELLM_MODEL.set("openai/other-model")
        try:
            assert router._effective_backend() is fake_other
        finally:
            CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)

    def test_effective_backend_same_as_default_skips_cache(
        self, default_llm: LiteLlm, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def _track(m: str) -> LiteLlm:
            calls.append(m)
            return default_llm

        monkeypatch.setattr(
            "agent.litellm_session_router._litellm_for_model_name",
            _track,
        )
        router = TelegramLitellmRouter.wrapping(default_llm)
        token = CURRENT_TELEGRAM_LITELLM_MODEL.set(default_llm.model)
        try:
            assert router._effective_backend() is default_llm
        finally:
            CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)

        assert calls == []

    def test_effective_backend_blank_context_uses_default(
        self, default_llm: LiteLlm
    ) -> None:
        router = TelegramLitellmRouter.wrapping(default_llm)
        token = CURRENT_TELEGRAM_LITELLM_MODEL.set("  \t  ")
        try:
            assert router._effective_backend() is default_llm
        finally:
            CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)

    def test_effective_backend_valueerror_falls_back(
        self,
        default_llm: LiteLlm,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _raise_litellm(_model_name: str) -> LiteLlm:
            raise ValueError("bad")

        monkeypatch.setattr(
            "agent.litellm_session_router._litellm_for_model_name",
            _raise_litellm,
        )
        router = TelegramLitellmRouter.wrapping(default_llm)
        token = CURRENT_TELEGRAM_LITELLM_MODEL.set("bad/model")
        try:
            assert router._effective_backend() is default_llm
        finally:
            CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)

        assert any(
            "Invalid or unsupported Telegram model" in r.message for r in caplog.records
        )


def test_litellm_for_model_name_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """lru_cache returns same instance for repeated model names."""
    _litellm_for_model_name.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    a = _litellm_for_model_name("gpt-4o-mini")
    b = _litellm_for_model_name("gpt-4o-mini")
    assert a is b
