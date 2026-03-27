"""Tests for Telegram LiteLLM routing wrapper."""

from collections.abc import AsyncIterator, Generator
from unittest.mock import MagicMock, patch

import pytest
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from litellm.exceptions import InternalServerError

from agent.litellm_session_router import (
    _DEFAULT_FALLBACK_MODEL_ID,
    CURRENT_TELEGRAM_LITELLM_MODEL,
    TelegramLitellmRouter,
    _cached_fallback_litellm,
    _fallback_model_id_from_env,
    _litellm_for_model_name,
    _llm_request_aligned_to_backend,
    _resolve_fallback_backend,
)


@pytest.fixture(autouse=True)
def _clear_fallback_litellm_cache() -> Generator[None]:
    _cached_fallback_litellm.cache_clear()
    yield
    _cached_fallback_litellm.cache_clear()


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


class _FailingBackend:
    """Async generator that raises before yielding (connection-style failure)."""

    def __init__(self, model_id: str, exc: BaseException) -> None:
        self.model = model_id
        self._exc = exc

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncIterator[object]:
        raise self._exc
        yield None  # type: ignore[unreachable]  # pragma: no cover


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

    @pytest.mark.asyncio
    async def test_generate_retries_on_internal_error_with_fallback(
        self,
        default_llm: LiteLlm,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        router = TelegramLitellmRouter.wrapping(default_llm)
        primary = _FailingBackend(
            "openai/glm-4.7",
            InternalServerError("Connection error", llm_provider="openai", model="x"),
        )
        mock_resp = MagicMock()
        fallback = _FakeBackend("openrouter/z-ai/glm-4.7", [mock_resp])
        req = LlmRequest(model=default_llm.model, contents=[])

        with (
            patch.object(router, "_effective_backend", return_value=primary),
            patch(
                "agent.litellm_session_router._resolve_fallback_backend",
                return_value=fallback,
            ),
        ):
            out = [x async for x in router.generate_content_async(req, stream=False)]

        assert out == [mock_resp]
        assert len(fallback.calls) == 1
        sent_fb, _stream = fallback.calls[0]
        assert isinstance(sent_fb, LlmRequest)
        assert sent_fb.model == "openrouter/z-ai/glm-4.7"
        assert any("retrying with fallback" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_generate_propagates_when_no_fallback(
        self,
        default_llm: LiteLlm,
    ) -> None:
        router = TelegramLitellmRouter.wrapping(default_llm)
        exc = InternalServerError("down", llm_provider="openai", model="x")
        primary = _FailingBackend("openai/glm-4.7", exc)
        req = LlmRequest(model=default_llm.model, contents=[])

        with (
            patch.object(router, "_effective_backend", return_value=primary),
            patch(
                "agent.litellm_session_router._resolve_fallback_backend",
                return_value=None,
            ),
            pytest.raises(InternalServerError),
        ):
            async for _ in router.generate_content_async(req, stream=False):
                pass

    @pytest.mark.asyncio
    async def test_generate_does_not_fallback_after_partial_stream(
        self,
        default_llm: LiteLlm,
    ) -> None:
        class _PartialThenFail:
            model = "openai/glm-4.7"

            async def generate_content_async(
                self,
                llm_request: LlmRequest,
                stream: bool = False,
            ) -> AsyncIterator[object]:
                yield MagicMock()
                raise InternalServerError("late", llm_provider="openai", model="x")

        router = TelegramLitellmRouter.wrapping(default_llm)
        req = LlmRequest(model=default_llm.model, contents=[])
        partial_backend = _PartialThenFail()

        with (
            patch.object(
                router,
                "_effective_backend",
                return_value=partial_backend,
            ),
            patch(
                "agent.litellm_session_router._resolve_fallback_backend",
                side_effect=AssertionError("fallback should not run"),
            ),
        ):
            gen = router.generate_content_async(req, stream=False)
            first = await gen.__anext__()
            assert first is not None
            with pytest.raises(InternalServerError):
                await gen.__anext__()


def test_litellm_for_model_name_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """lru_cache returns same instance for repeated model names."""
    _litellm_for_model_name.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    a = _litellm_for_model_name("gpt-4o-mini")
    b = _litellm_for_model_name("gpt-4o-mini")
    assert a is b


class TestFallbackEnvResolution:
    """``LITELLM_FALLBACK_MODEL`` and helper coverage."""

    def test_fallback_model_unset_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LITELLM_FALLBACK_MODEL", raising=False)
        assert _fallback_model_id_from_env() == _DEFAULT_FALLBACK_MODEL_ID

    def test_fallback_model_empty_disables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_FALLBACK_MODEL", "  ")
        assert _fallback_model_id_from_env() is None

    def test_fallback_model_explicit_strips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "LITELLM_FALLBACK_MODEL",
            "  openrouter/custom/model  ",
        )
        assert _fallback_model_id_from_env() == "openrouter/custom/model"

    def test_resolve_fallback_none_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_FALLBACK_MODEL", "")
        assert _resolve_fallback_backend("openai/glm-4.7") is None

    def test_resolve_fallback_none_when_same_as_primary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LITELLM_FALLBACK_MODEL", raising=False)
        same = _DEFAULT_FALLBACK_MODEL_ID
        assert _resolve_fallback_backend(same) is None

    def test_resolve_fallback_returns_litellm_when_primary_differs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cached_fallback_litellm.cache_clear()
        monkeypatch.delenv("LITELLM_FALLBACK_MODEL", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        fb = _resolve_fallback_backend("openai/glm-4.7")
        assert fb is not None
        assert fb.model == _DEFAULT_FALLBACK_MODEL_ID

    def test_cached_fallback_warns_and_returns_none_on_valueerror(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _cached_fallback_litellm.cache_clear()

        def _bad(_mid: str) -> dict[str, str]:
            raise ValueError("no key")

        monkeypatch.setattr(
            "agent.litellm_session_router.build_litellm_kwargs",
            _bad,
        )
        assert _cached_fallback_litellm("openrouter/x") is None
        assert any(
            "not usable" in r.message and "connection fallbacks disabled" in r.message
            for r in caplog.records
        )

    def test_cached_fallback_builds_litellm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cached_fallback_litellm.cache_clear()
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        fb = _cached_fallback_litellm("openrouter/z-ai/glm-4.7")
        assert fb is not None
        assert fb.model == "openrouter/z-ai/glm-4.7"
