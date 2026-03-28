"""Tests for TelegramLitellmRequestModelPlugin."""

from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_request import LlmRequest

from agent.litellm_session_router import CURRENT_TELEGRAM_LITELLM_MODEL
from agent.telegram import TelegramLitellmRequestModelPlugin


@pytest.mark.asyncio
async def test_plugin_sets_llm_request_model_from_context_var() -> None:
    plugin = TelegramLitellmRequestModelPlugin()
    req = LlmRequest(model="openai/glm-4.7", contents=[])
    token = CURRENT_TELEGRAM_LITELLM_MODEL.set("openai/glm-5")
    try:
        await plugin.before_model_callback(
            callback_context=MagicMock(),
            llm_request=req,
        )
    finally:
        CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)

    assert req.model == "openai/glm-5"


@pytest.mark.asyncio
async def test_plugin_noop_when_context_unset() -> None:
    plugin = TelegramLitellmRequestModelPlugin()
    req = LlmRequest(model="openai/glm-4.7", contents=[])
    await plugin.before_model_callback(
        callback_context=MagicMock(),
        llm_request=req,
    )
    assert req.model == "openai/glm-4.7"


@pytest.mark.asyncio
async def test_plugin_noop_when_context_blank() -> None:
    plugin = TelegramLitellmRequestModelPlugin()
    req = LlmRequest(model="openai/glm-4.7", contents=[])
    token = CURRENT_TELEGRAM_LITELLM_MODEL.set("  ")
    try:
        await plugin.before_model_callback(
            callback_context=MagicMock(),
            llm_request=req,
        )
    finally:
        CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)

    assert req.model == "openai/glm-4.7"
