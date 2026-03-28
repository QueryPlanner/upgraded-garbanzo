"""Sync ``LlmRequest.model`` with Telegram's per-chat LiteLLM id for accurate logs.

``LoggingPlugin`` prints ``llm_request.model``, which ADK fills from the root
agent's default. Telegram overrides the real completion via
``CURRENT_TELEGRAM_LITELLM_MODEL``; this plugin copies that value onto the
request *before* ``LoggingPlugin`` runs so console output matches LiteLLM.
"""

from __future__ import annotations

from typing import override

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from ..litellm_session_router import CURRENT_TELEGRAM_LITELLM_MODEL


class TelegramLitellmRequestModelPlugin(BasePlugin):
    """When Telegram has set the context var, align ``LlmRequest.model`` early."""

    def __init__(self, name: str = "telegram_litellm_request_model") -> None:
        super().__init__(name=name)

    @override
    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        _ = callback_context
        raw = CURRENT_TELEGRAM_LITELLM_MODEL.get()
        if raw is None:
            return None
        stripped = str(raw).strip()
        if not stripped:
            return None
        llm_request.model = stripped
        return None
