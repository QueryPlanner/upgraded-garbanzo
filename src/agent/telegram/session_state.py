"""Persist Telegram-only session fields through the ADK session service."""

from __future__ import annotations

import logging
from typing import Any

from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions.base_session_service import BaseSessionService

logger = logging.getLogger(__name__)


async def merge_session_state_delta(
    session_service: BaseSessionService,
    *,
    app_name: str,
    user_id: str,
    session_id: str,
    state_delta: dict[str, Any],
) -> None:
    """Apply ``state_delta`` to session state (creates session if missing)."""
    if not state_delta:
        return

    session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

    if session is None:
        initial: dict[str, Any] = {"user_id": user_id, **state_delta}
        await session_service.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state=initial,
        )
        logger.info(
            "Created session with telegram state keys: %s",
            list(state_delta.keys()),
        )
        return

    event = Event(
        author="user",
        invocation_id="telegram-command",
        actions=EventActions(state_delta=dict(state_delta)),
    )
    await session_service.append_event(session, event)
    logger.info("Merged telegram session delta keys: %s", list(state_delta.keys()))
