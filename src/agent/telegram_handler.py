"""Telegram bot integration for ADK agent.

This module provides a Telegram bot that bridges messages between Telegram
and the ADK agent, allowing users to interact with the agent via Telegram.
"""

import logging

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

logger = logging.getLogger(__name__)


class TelegramHandler:
    """Handler for processing Telegram messages through an ADK agent.

    This class encapsulates the runner and session management for the ADK agent,
    providing a clean interface for processing Telegram messages.

    Attributes:
        agent: The LlmAgent used for processing messages.
        runner: The InMemoryRunner instance for running the agent.
        app_name: The application name for session management.
    """

    def __init__(self, agent: LlmAgent, app_name: str = "telegram-bot") -> None:
        """Initialize the TelegramHandler with an ADK agent.

        Args:
            agent: The LlmAgent to use for processing messages.
            app_name: Application name for session management.
        """
        self.agent = agent
        self.app_name = app_name
        self.runner = InMemoryRunner(agent=agent, app_name=app_name)
        logger.info(f"ADK Runner initialized with app_name={app_name}")

    async def process_message(
        self,
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
        """
        # Use user_id as session_id if not provided
        effective_session_id = session_id or user_id

        # Create or get existing session
        session = await self.runner.session_service.get_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=effective_session_id,
        )

        if session is None:
            session = await self.runner.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=effective_session_id,
            )

        # Create the user message
        content = types.Content(role="user", parts=[types.Part(text=message)])

        # Run the agent and collect the response
        response_parts: list[str] = []
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=effective_session_id,
            new_message=content,
        ):
            # Extract text from model responses, filtering out thought parts
            # Thought parts contain internal reasoning and should not be shown to users
            if event.content and event.content.parts:
                for part in event.content.parts:
                    # Skip thought parts (internal model reasoning)
                    # Note: The 'thought' attribute is used by Google's ADK to mark
                    # internal reasoning parts. This approach relies on the internal
                    # structure of google.genai.types.Part. If the library changes,
                    # this logic may need to be updated.
                    if hasattr(part, "thought") and part.thought:
                        continue
                    if part.text:
                        response_parts.append(part.text)

        return "".join(response_parts)

    async def reset_session(self, user_id: str, session_id: str | None = None) -> bool:
        """Reset a user's session by deleting and creating a fresh one.

        This method deletes the existing session and creates a new one immediately,
        providing a complete reset of conversation state.

        Args:
            user_id: The user's unique identifier.
            session_id: Optional specific session ID. Uses user_id if not provided.

        Returns:
            True if session was reset successfully, False otherwise.
        """
        effective_session_id = session_id or user_id

        try:
            # Delete existing session if it exists
            await self.runner.session_service.delete_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=effective_session_id,
            )
            logger.info(
                f"Deleted existing session for user={user_id}, "
                f"session={effective_session_id}"
            )
        except Exception:
            # This is not critical, as the session might not have existed.
            # We log it as a warning and proceed to creation.
            logger.warning(
                f"Could not delete session for user={user_id}, "
                f"session={effective_session_id}. "
                "It might not have existed. Proceeding with session creation."
            )

        try:
            # The crucial part is creating a new session.
            await self.runner.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=effective_session_id,
            )
            logger.info(
                f"Created new session for user={user_id}, "
                f"session={effective_session_id}"
            )
            return True
        except Exception:
            logger.exception(
                f"Failed to create new session for user={user_id}, "
                f"session={effective_session_id}"
            )
            return False


# Global handler instance for backwards compatibility with module-level functions
_handler: TelegramHandler | None = None


def initialize_runner(
    agent: LlmAgent, app_name: str = "telegram-bot"
) -> InMemoryRunner:
    """Initialize the ADK runner with the given agent.

    This function is maintained for backwards compatibility.
    Consider using the TelegramHandler class directly for new code.

    Args:
        agent: The LlmAgent to use for processing messages.
        app_name: Application name for session management.

    Returns:
        Initialized InMemoryRunner instance.
    """
    global _handler
    _handler = TelegramHandler(agent=agent, app_name=app_name)
    return _handler.runner


async def process_message(
    user_id: str,
    message: str,
    session_id: str | None = None,
) -> str:
    """Process a message through the ADK agent.

    This function is maintained for backwards compatibility.
    Consider using the TelegramHandler class directly for new code.

    Args:
        user_id: Unique identifier for the user (e.g., Telegram chat ID).
        message: The message text to process.
        session_id: Optional session ID for conversation continuity.
            If not provided, user_id is used as session_id.

    Returns:
        The agent's response text.

    Raises:
        RuntimeError: If the handler hasn't been initialized.
    """
    if _handler is None:
        raise RuntimeError("Handler not initialized. Call initialize_runner() first.")
    return await _handler.process_message(
        user_id=user_id, message=message, session_id=session_id
    )


async def reset_session(user_id: str, session_id: str | None = None) -> bool:
    """Reset a user's session by deleting and creating a fresh one.

    This function is maintained for backwards compatibility.
    Consider using the TelegramHandler class directly for new code.

    Args:
        user_id: The user's unique identifier.
        session_id: Optional specific session ID. Uses user_id if not provided.

    Returns:
        True if session was reset successfully, False otherwise.
    """
    if _handler is None:
        return False
    return await _handler.reset_session(user_id=user_id, session_id=session_id)
