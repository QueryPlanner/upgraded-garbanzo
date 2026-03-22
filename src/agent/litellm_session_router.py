"""Per-request LiteLLM routing for Telegram via a context variable.

When ``CURRENT_TELEGRAM_LITELLM_MODEL`` is unset (e.g. FastAPI server), the
default ``LiteLlm`` from the environment is used. Telegram sets the context
var around ``run_async`` to the resolved model for that chat session.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from functools import lru_cache
from typing import override

from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from pydantic import ConfigDict, Field

from .litellm_config import build_litellm_kwargs

logger = logging.getLogger(__name__)

CURRENT_TELEGRAM_LITELLM_MODEL: ContextVar[str | None] = ContextVar(
    "CURRENT_TELEGRAM_LITELLM_MODEL",
    default=None,
)


@lru_cache(maxsize=32)
def _litellm_for_model_name(model_name: str) -> LiteLlm:
    """Return a cached LiteLlm for ``model_name`` (process env must be configured)."""
    kwargs = build_litellm_kwargs(model_name)
    return LiteLlm(**kwargs)


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
        async for chunk in backend.generate_content_async(aligned, stream=stream):
            yield chunk
