"""Telegram bot integration for ADK agent.

This module provides a Telegram bot that bridges messages between Telegram
and the ADK agent, allowing users to interact with the agent via Telegram.
"""

import logging

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

logger = logging.getLogger(__name__)

# Global runner instance (initialized lazily)
_runner: InMemoryRunner | None = None
_agent: LlmAgent | None = None


def initialize_runner(
    agent: LlmAgent, app_name: str = "telegram-bot"
) -> InMemoryRunner:
    """Initialize the ADK runner with the given agent.

    Args:
        agent: The LlmAgent to use for processing messages.
        app_name: Application name for session management.

    Returns:
        Initialized InMemoryRunner instance.
    """
    global _runner, _agent
    _agent = agent
    _runner = InMemoryRunner(agent=agent, app_name=app_name)
    logger.info(f"ADK Runner initialized with app_name={app_name}")
    return _runner


async def process_message(
    user_id: str,
    message: str,
    session_id: str | None = None,
) -> str:
    """Process a message through the ADK agent.

    Args:
        user_id: Unique identifier for the user (e.g., Telegram chat ID).
        message: The message text to process.
        session_id: Optional session ID for conversation continuity.
            If not provided, user_id is used as session_id.

    Returns:
        The agent's response text.

    Raises:
        RuntimeError: If the runner hasn't been initialized.
    """
    if _runner is None:
        raise RuntimeError("Runner not initialized. Call initialize_runner() first.")

    # Use user_id as session_id if not provided
    effective_session_id = session_id or user_id

    # Create or get existing session
    session = await _runner.session_service.get_session(
        app_name=_runner.app_name,
        user_id=user_id,
        session_id=effective_session_id,
    )

    if session is None:
        session = await _runner.session_service.create_session(
            app_name=_runner.app_name,
            user_id=user_id,
            session_id=effective_session_id,
        )

    # Create the user message
    content = types.Content(role="user", parts=[types.Part(text=message)])

    # Run the agent and collect the response
    response_parts: list[str] = []
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=effective_session_id,
        new_message=content,
    ):
        # Extract text from model responses, filtering out thought parts
        # Thought parts contain internal reasoning and should not be shown to users
        if event.content and event.content.parts:
            for part in event.content.parts:
                # Skip thought parts (internal model reasoning)
                if hasattr(part, "thought") and part.thought:
                    continue
                if part.text:
                    response_parts.append(part.text)

    return "".join(response_parts)


async def clear_session(user_id: str, session_id: str | None = None) -> bool:
    """Clear a user's session to start a fresh conversation.

    Args:
        user_id: The user's unique identifier.
        session_id: Optional specific session ID. Uses user_id if not provided.

    Returns:
        True if session was cleared, False if it didn't exist.
    """
    if _runner is None:
        return False

    effective_session_id = session_id or user_id

    try:
        await _runner.session_service.delete_session(
            app_name=_runner.app_name,
            user_id=user_id,
            session_id=effective_session_id,
        )
        logger.info(
            f"Cleared session for user={user_id}, session={effective_session_id}"
        )
        return True
    except Exception:
        return False
