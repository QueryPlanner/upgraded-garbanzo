"""Tests for Telegram session state merges via ADK session service."""

import pytest
from google.adk.sessions.in_memory_session_service import InMemorySessionService

from agent.telegram import TELEGRAM_SESSION_LITELLM_MODEL_KEY
from agent.telegram.session_state import merge_session_state_delta


@pytest.mark.asyncio
async def test_merge_creates_session_when_missing() -> None:
    svc = InMemorySessionService()
    await merge_session_state_delta(
        svc,
        app_name="agent",
        user_id="u1",
        session_id="u1",
        state_delta={TELEGRAM_SESSION_LITELLM_MODEL_KEY: "openai/glm-5"},
    )
    session = await svc.get_session(
        app_name="agent",
        user_id="u1",
        session_id="u1",
    )
    assert session is not None
    assert session.state.get(TELEGRAM_SESSION_LITELLM_MODEL_KEY) == "openai/glm-5"
    assert session.state.get("user_id") == "u1"


@pytest.mark.asyncio
async def test_merge_appends_event_when_session_exists() -> None:
    svc = InMemorySessionService()
    await svc.create_session(
        app_name="agent",
        user_id="u1",
        session_id="u1",
        state={"user_id": "u1"},
    )
    await merge_session_state_delta(
        svc,
        app_name="agent",
        user_id="u1",
        session_id="u1",
        state_delta={TELEGRAM_SESSION_LITELLM_MODEL_KEY: "openrouter/z-ai/glm-4.7"},
    )
    session = await svc.get_session(
        app_name="agent",
        user_id="u1",
        session_id="u1",
    )
    assert session is not None
    assert session.state.get(TELEGRAM_SESSION_LITELLM_MODEL_KEY) == (
        "openrouter/z-ai/glm-4.7"
    )


@pytest.mark.asyncio
async def test_merge_empty_delta_noop() -> None:
    svc = InMemorySessionService()
    await merge_session_state_delta(
        svc,
        app_name="agent",
        user_id="u1",
        session_id="u1",
        state_delta={},
    )
    session = await svc.get_session(
        app_name="agent",
        user_id="u1",
        session_id="u1",
    )
    assert session is None
