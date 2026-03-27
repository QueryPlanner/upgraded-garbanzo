"""Per-request LiteLLM routing for Telegram via a context variable.

When ``CURRENT_TELEGRAM_LITELLM_MODEL`` is unset (e.g. FastAPI server), the
default ``LiteLlm`` from the environment is used. Telegram sets the context
var around ``run_async`` to the resolved model for that chat session.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from functools import lru_cache
from typing import override

from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from litellm.exceptions import (
    APIConnectionError,
    BadGatewayError,
    InternalServerError,
    ServiceUnavailableError,
)
from litellm.exceptions import (
    Timeout as LitellmTimeout,
)
from pydantic import ConfigDict, Field

from .litellm_config import build_litellm_kwargs

logger = logging.getLogger(__name__)

# Default when ``LITELLM_FALLBACK_MODEL`` is unset (OpenRouter GLM 4.7).
_DEFAULT_FALLBACK_MODEL_ID = "openrouter/z-ai/glm-4.7"

_RETRYABLE_LITELLM_ERRORS: tuple[type[Exception], ...] = (
    APIConnectionError,
    InternalServerError,
    ServiceUnavailableError,
    BadGatewayError,
    LitellmTimeout,
)

CURRENT_TELEGRAM_LITELLM_MODEL: ContextVar[str | None] = ContextVar(
    "CURRENT_TELEGRAM_LITELLM_MODEL",
    default=None,
)


@lru_cache(maxsize=32)
def _litellm_for_model_name(model_name: str) -> LiteLlm:
    """Return a cached LiteLlm for ``model_name`` (process env must be configured)."""
    kwargs = build_litellm_kwargs(model_name)
    return LiteLlm(**kwargs)


def _fallback_model_id_from_env() -> str | None:
    """Return fallback LiteLLM model id, or ``None`` if fallback is disabled."""
    raw = os.getenv("LITELLM_FALLBACK_MODEL")
    if raw is None:
        return _DEFAULT_FALLBACK_MODEL_ID
    stripped = raw.strip()
    return stripped or None


@lru_cache(maxsize=8)
def _cached_fallback_litellm(fallback_model_id: str) -> LiteLlm | None:
    try:
        kwargs = build_litellm_kwargs(fallback_model_id)
    except ValueError as exc:
        logger.warning(
            "LITELLM_FALLBACK_MODEL %r not usable (%s); connection fallbacks disabled",
            fallback_model_id,
            exc,
        )
        return None
    return LiteLlm(**kwargs)


def _resolve_fallback_backend(primary_model: str) -> LiteLlm | None:
    """OpenRouter (or other) backend used when the primary endpoint fails to connect."""
    fallback_id = _fallback_model_id_from_env()
    if fallback_id is None:
        return None
    if fallback_id == primary_model:
        return None
    return _cached_fallback_litellm(fallback_id)


def _llm_request_aligned_to_backend(
    llm_request: LlmRequest,
    backend: LiteLlm,
) -> LlmRequest:
    """Ensure ``LlmRequest.model`` matches the backend LiteLlm instance.

    ADK fills ``LlmRequest.model`` from the root agent's ``model`` field (this
    router's Pydantic ``model``, i.e. ``ROOT_AGENT_MODEL``). LiteLLM then uses
    ``llm_request.model or self.model``, so a stale request model would override
    the delegated backend and ignore Telegram session overrides.
    """
    backend_model = backend.model
    request_model = llm_request.model
    if request_model is None or request_model == backend_model:
        return llm_request
    return llm_request.model_copy(update={"model": backend_model})


class TelegramLitellmRouter(BaseLlm):
    """Delegates to the default LiteLlm or a per-model cached instance."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    default_llm: LiteLlm = Field(...)
    """Environment-backed LiteLlm (``ROOT_AGENT_MODEL``)."""

    @classmethod
    def wrapping(cls, default_llm: LiteLlm) -> TelegramLitellmRouter:
        """Build a router whose fallback matches ``ROOT_AGENT_MODEL``."""
        return cls.model_validate(
            {"model": default_llm.model, "default_llm": default_llm},
        )

    def _effective_backend(self) -> LiteLlm:
        override_id = CURRENT_TELEGRAM_LITELLM_MODEL.get()
        if override_id is None or not override_id.strip():
            return self.default_llm
        stripped = override_id.strip()
        if stripped == self.default_llm.model:
            return self.default_llm
        try:
            return _litellm_for_model_name(stripped)
        except ValueError:
            logger.warning(
                "Invalid or unsupported Telegram model override %r; using default %s",
                stripped,
                self.default_llm.model,
            )
            return self.default_llm

    @override
    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse]:
        backend = self._effective_backend()
        aligned = _llm_request_aligned_to_backend(llm_request, backend)
        yielded_any = False
        try:
            async for chunk in backend.generate_content_async(aligned, stream=stream):
                yielded_any = True
                yield chunk
        except _RETRYABLE_LITELLM_ERRORS as first_exc:
            if yielded_any:
                raise
            fallback_llm = _resolve_fallback_backend(backend.model)
            if fallback_llm is None:
                raise first_exc
            logger.warning(
                "Primary LLM %r failed (%s); retrying with fallback %r",
                backend.model,
                first_exc,
                fallback_llm.model,
            )
            aligned_fb = _llm_request_aligned_to_backend(llm_request, fallback_llm)
            async for chunk in fallback_llm.generate_content_async(
                aligned_fb,
                stream=stream,
            ):
                yield chunk
