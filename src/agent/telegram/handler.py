"""Telegram bot integration for ADK agent.

This module provides a Telegram bot that bridges messages between Telegram
and the ADK agent, allowing users to interact with the agent via Telegram.
"""

import logging
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import InMemoryRunner, Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import types

from ..utils.app_timezone import format_stored_instant_for_display

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _telegram_latency_log_enabled() -> bool:
    """True when TELEGRAM_LATENCY_LOG requests structured pre-LLM timing logs."""
    value = os.environ.get("TELEGRAM_LATENCY_LOG", "").strip().lower()
    return value in ("1", "true", "yes")


# Template for injecting reminders into the agent's context
REMINDER_PROMPT_TEMPLATE = """[SCHEDULED REMINDER]

Send the user a short message that delivers only this reminder (scheduled for
{scheduled_time}):

"{reminder_message}"

Rules: Your reply is what they see in Telegram. Stay on-topic: remind them of the
above, briefly and in a natural tone. Do not invite unrelated tasks, logging,
recipes, tips, or “let me know if you need anything else” — no add-ons beyond the
reminder itself."""


class TelegramHandler:
    """Handler for processing Telegram messages through an ADK agent.

    This class encapsulates the runner and session management for the ADK agent,
    providing a clean interface for processing Telegram messages.

    Attributes:
        agent: The LlmAgent used for processing messages.
        runner: The Runner instance for running the agent (in-memory or DB-backed).
        app_name: The application name for session management.
    """

    def __init__(
        self,
        agent: LlmAgent | None = None,
        app: App | None = None,
        app_name: str = "telegram-bot",
        session_service: BaseSessionService | None = None,
    ) -> None:
        """Initialize the TelegramHandler with an ADK agent or App.

        Args:
            agent: The LlmAgent to use for processing messages. Use either
                this or 'app', not both.
            app: An App instance with pre-configured plugins (like
                GlobalInstructionPlugin for current time). If provided, this
                takes precedence over agent parameter.
            app_name: Application name for session management.
            session_service: Optional session service for persistence. When
                provided (e.g., Postgres via DATABASE_URL), sessions survive
                restarts. When None, uses InMemoryRunner (sessions lost on restart).
        """
        if app is not None:
            # Use the App's plugins (like GlobalInstructionPlugin for current time)
            self.agent = app.root_agent
            self.app_name = app.name

            # Create runner with the app and its plugins
            if session_service is not None:
                self.runner = Runner(
                    app=app,
                    session_service=session_service,
                    artifact_service=InMemoryArtifactService(),
                    memory_service=InMemoryMemoryService(),
                )
                logger.info(
                    f"TelegramHandler initialized from App with plugins "
                    f"(app_name={self.app_name}, database-backed sessions)"
                )
            else:
                self.runner = InMemoryRunner(
                    app=app,
                )
                logger.info(
                    f"TelegramHandler initialized from App with plugins "
                    f"(app_name={self.app_name}, in-memory sessions)"
                )
        elif agent is not None:
            self.agent = agent
            self.app_name = app_name

            if session_service is not None:
                self.runner = Runner(
                    agent=agent,
                    app_name=app_name,
                    session_service=session_service,
                    artifact_service=InMemoryArtifactService(),
                    memory_service=InMemoryMemoryService(),
                )
                logger.info(
                    f"ADK Runner initialized with app_name={app_name} "
                    "(database-backed sessions)"
                )
            else:
                self.runner = InMemoryRunner(agent=agent, app_name=app_name)
                logger.info(
                    f"ADK Runner initialized with app_name={app_name} "
                    "(in-memory sessions)"
                )
        else:
            raise ValueError("Either 'agent' or 'app' must be provided")

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
        latency_log = _telegram_latency_log_enabled()
        pipeline_start = time.perf_counter()

        # Use user_id as session_id if not provided
        effective_session_id = session_id or user_id

        # Create or get existing session
        session = await self.runner.session_service.get_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=effective_session_id,
        )

        if session is None:
            # Create session with initial state containing user_id
            session = await self.runner.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=effective_session_id,
                state={"user_id": user_id},
            )
            logger.info(f"Created new session with user_id={user_id}")
        else:
            # If user_id is missing from session state, delete and recreate
            # (modifying session.state in memory doesn't persist to database)
            if "user_id" not in session.state:
                logger.info(f"Session missing user_id, recreating for user={user_id}")
                try:
                    await self.runner.session_service.delete_session(
                        app_name=self.app_name,
                        user_id=user_id,
                        session_id=effective_session_id,
                    )
                except Exception:
                    logger.warning(
                        f"Could not delete session for user={user_id}, "
                        f"session={effective_session_id}. Proceeding with recreation."
                    )
                session = await self.runner.session_service.create_session(
                    app_name=self.app_name,
                    user_id=user_id,
                    session_id=effective_session_id,
                    state={"user_id": user_id},
                )
                logger.info(f"Recreated session with user_id={user_id}")

        logger.info(f"Session state keys: {list(session.state.keys())}")

        session_ready = time.perf_counter()

        # Create the user message
        content = types.Content(role="user", parts=[types.Part(text=message)])

        # Run the agent and collect the response
        response_parts: list[str] = []
        if latency_log:
            session_ms = (session_ready - pipeline_start) * 1000
            logger.info(
                "telegram.pre_llm_latency user_id=%s session_ms=%.1f "
                "(DB/session work in handler before run_async)",
                user_id,
                session_ms,
            )

        run_started = time.perf_counter()
        first_stream_event_logged = False
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=effective_session_id,
            new_message=content,
        ):
            if latency_log and not first_stream_event_logged:
                first_stream_event_logged = True
                first_event = time.perf_counter()
                ms_after_run = (first_event - run_started) * 1000
                logger.info(
                    "telegram.adk_first_stream_event user_id=%s "
                    "ms_after_run_async_started=%.1f "
                    "(often includes LLM; first yield may be late)",
                    user_id,
                    ms_after_run,
                )

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

        if latency_log and not first_stream_event_logged:
            logger.info(
                "telegram.adk_first_stream_event user_id=%s "
                "ms_after_run_async_started=n/a (run_async yielded no events)",
                user_id,
            )

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
            # The crucial part is creating a new session with initial state.
            await self.runner.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=effective_session_id,
                state={"user_id": user_id},
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

    async def process_reminder(
        self,
        user_id: str,
        reminder_message: str,
        scheduled_time: datetime,
        session_id: str | None = None,
    ) -> str:
        """Process a reminder through the ADK agent for personalized response.

        This method injects a reminder as a simulated user message, allowing
        the agent to generate a contextual, personalized response rather than
        sending a hardcoded notification.

        Args:
            user_id: Unique identifier for the user (e.g., Telegram chat ID).
            reminder_message: The original reminder message the user set.
            scheduled_time: When the reminder was scheduled for.
            session_id: Optional session ID for conversation continuity.
                If not provided, user_id is used as session_id.

        Returns:
            The agent's personalized response to the reminder.
        """
        if scheduled_time.tzinfo is None:
            scheduled_time = scheduled_time.replace(tzinfo=UTC)
        time_str = format_stored_instant_for_display(
            scheduled_time.astimezone(UTC).isoformat(timespec="seconds")
        )

        # Create the reminder prompt using the template
        prompt = REMINDER_PROMPT_TEMPLATE.format(
            reminder_message=reminder_message,
            scheduled_time=time_str,
        )

        logger.info(
            f"Processing reminder for user {user_id}: '{reminder_message[:30]}...'"
        )

        # Process through the agent using the existing message flow
        response = await self.process_message(
            user_id=user_id,
            message=prompt,
            session_id=session_id,
        )

        return response


# Global handler instance for backwards compatibility with module-level functions
_handler: TelegramHandler | None = None


def initialize_runner(
    agent: LlmAgent | None = None,
    app: App | None = None,
    app_name: str = "telegram-bot",
    session_service: BaseSessionService | None = None,
) -> Runner:
    """Initialize the ADK runner with the given agent or app.

    This function is maintained for backwards compatibility.
    Consider using the TelegramHandler class directly for new code.

    Args:
        agent: The LlmAgent to use for processing messages. Use either
            this or 'app', not both.
        app: An App instance with pre-configured plugins (like
            GlobalInstructionPlugin for current time). If provided, this
            takes precedence over agent parameter.
        app_name: Application name for session management.
        session_service: Optional session service. When provided (e.g., from
            DATABASE_URL), sessions persist across restarts.

    Returns:
        Initialized Runner instance (InMemoryRunner or Runner with DB-backed
        session service).
    """
    global _handler
    _handler = TelegramHandler(
        agent=agent,
        app=app,
        app_name=app_name,
        session_service=session_service,
    )
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


def get_handler() -> TelegramHandler | None:
    """Get the global TelegramHandler instance.

    Returns:
        The global TelegramHandler instance, or None if not initialized.
    """
    return _handler
