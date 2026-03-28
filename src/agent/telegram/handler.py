"""Telegram bot integration for ADK agent.

This module provides a Telegram bot that bridges messages between Telegram
and the ADK agent, allowing users to interact with the agent via Telegram.
"""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import InMemoryRunner, Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import types

from ..litellm_session_router import CURRENT_TELEGRAM_LITELLM_MODEL
from ..utils.app_timezone import format_stored_instant_for_display
from ..utils.telegram_outbox import (
    PendingTelegramFile,
    begin_telegram_file_batch,
    discard_telegram_staging_files,
    end_telegram_file_batch,
)
from .model_settings import default_root_model
from .prefs import TELEGRAM_SESSION_LITELLM_MODEL_KEY

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _read_litellm_model_from_state(state: dict[str, Any] | None) -> str | None:
    if not state:
        return None
    raw = state.get(TELEGRAM_SESSION_LITELLM_MODEL_KEY)
    if isinstance(raw, str):
        stripped = raw.strip()
        return stripped or None
    return None


@asynccontextmanager
async def _telegram_litellm_model_context(model_id: str) -> AsyncIterator[None]:
    token = CURRENT_TELEGRAM_LITELLM_MODEL.set(model_id)
    try:
        yield
    finally:
        CURRENT_TELEGRAM_LITELLM_MODEL.reset(token)


@dataclass(frozen=True)
class TelegramAgentReply:
    """Text response from the agent plus files queued for Telegram."""

    text: str
    documents: tuple[PendingTelegramFile, ...] = field(default_factory=tuple)
    superseded: bool = False
    streamed_text: bool = False


class TelegramTurnSupersededError(asyncio.CancelledError):
    """Raised when a newer Telegram message replaces an in-flight turn."""


@dataclass
class _ActiveTelegramTurn:
    """Track the current in-flight turn for one Telegram conversation."""

    request_id: int
    task: asyncio.Task[TelegramAgentReply]


@dataclass
class _TelegramConversationState:
    """Mutable coordination state for one Telegram conversation."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_request_id: int = 0
    active_turn: _ActiveTelegramTurn | None = None
    superseded_request_ids: set[int] = field(default_factory=set)


def _telegram_latency_log_enabled() -> bool:
    """True when TELEGRAM_LATENCY_LOG requests structured pre-LLM timing logs."""
    value = os.environ.get("TELEGRAM_LATENCY_LOG", "").strip().lower()
    return value in ("1", "true", "yes")


# Suffix for ADK session IDs used when delivering scheduled reminders so they do not
# overwrite the user's main chat session.
REMINDER_SESSION_SUFFIX = "-reminder"

# Template for injecting reminders into the agent's context
REMINDER_PROMPT_TEMPLATE = """[SCHEDULED REMINDER]

This reminder has already been scheduled and is firing now.

Scheduled time: {scheduled_time}

Reminder instruction:

"{reminder_message}"

Rules:
- Your reply is the final Telegram message the user sees right now.
- Do not call tools.
- Do not schedule, reschedule, validate, or discuss reminder times.
- Do not say the scheduled time is in the past. The reminder is already firing.
- If the reminder instruction asks for generated content, generate it directly.
- Stay on-topic and do not add unrelated tasks, logging, recipes, tips, or
  “let me know if you need anything else”."""

# Injected as a user turn when a background Claude Code job finishes (Telegram).
CLAUDE_JOB_COMPLETION_TEMPLATE = """[CLAUDE CODING JOB COMPLETE]

Job id: {job_id}
Workdir: {cwd}
Status: {status}
Exit code: {exit_code}
{truncated_line}

--- stdout ---
{stdout_section}

--- stderr ---
{stderr_section}

The background Claude Code run you started has finished. The raw subprocess output
was also posted to this chat in separate messages.

Summarize what happened for the user, call out errors or follow-ups, and propose
concrete next steps (e.g. re-run the coding tool, verify CI, or ask one focused
question). You may use tools if needed to verify or continue the task."""


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

        self._conversation_states: dict[
            tuple[str, str], _TelegramConversationState
        ] = {}
        self._conversation_states_lock = asyncio.Lock()

    async def _get_conversation_state(
        self,
        user_id: str,
        session_id: str,
    ) -> _TelegramConversationState:
        """Return the mutable turn state for one Telegram conversation."""
        conversation_key = (user_id, session_id)

        async with self._conversation_states_lock:
            existing_state = self._conversation_states.get(conversation_key)
            if existing_state is not None:
                return existing_state

            new_state = _TelegramConversationState()
            self._conversation_states[conversation_key] = new_state
            return new_state

    async def _clear_conversation_state_if_idle(
        self,
        user_id: str,
        session_id: str,
        conversation_state: _TelegramConversationState,
    ) -> None:
        """Drop idle coordination state so finished chats do not accumulate."""
        async with conversation_state.lock:
            has_active_turn = conversation_state.active_turn is not None
            has_superseded_requests = bool(conversation_state.superseded_request_ids)
            has_seen_requests = conversation_state.next_request_id > 0

        if has_active_turn or has_superseded_requests or not has_seen_requests:
            return

        conversation_key = (user_id, session_id)
        async with self._conversation_states_lock:
            cached_state = self._conversation_states.get(conversation_key)
            if cached_state is conversation_state:
                self._conversation_states.pop(conversation_key, None)

    async def _consume_superseded_request(
        self,
        conversation_state: _TelegramConversationState,
        request_id: int,
    ) -> bool:
        """Return True once for requests that were intentionally replaced."""
        async with conversation_state.lock:
            if request_id not in conversation_state.superseded_request_ids:
                return False

            conversation_state.superseded_request_ids.remove(request_id)
            return True

    async def _cancel_active_turn(
        self,
        user_id: str,
        session_id: str,
    ) -> None:
        """Cancel any in-flight turn for the conversation and suppress its reply."""
        conversation_state = await self._get_conversation_state(user_id, session_id)

        async with conversation_state.lock:
            active_turn = conversation_state.active_turn
            if active_turn is None or active_turn.task.done():
                return

            conversation_state.superseded_request_ids.add(active_turn.request_id)
            active_task = active_turn.task
            active_task.cancel()

        with suppress(asyncio.CancelledError):
            await active_task

        await self._clear_conversation_state_if_idle(
            user_id=user_id,
            session_id=session_id,
            conversation_state=conversation_state,
        )

    def _resolve_litellm_model_for_session_state(
        self,
        session_state: dict[str, Any] | None,
        *,
        force_litellm_model: str | None,
    ) -> str:
        if force_litellm_model is not None and force_litellm_model.strip():
            return force_litellm_model.strip()
        override = _read_litellm_model_from_state(session_state)
        if override is not None:
            return override
        return default_root_model()

    async def process_message(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
        force_litellm_model: str | None = None,
        on_text_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> TelegramAgentReply:
        """Process a message through the ADK agent.

        Args:
            user_id: Unique identifier for the user (e.g., Telegram chat ID).
            message: The message text to process.
            session_id: Optional session ID for conversation continuity.
                If not provided, user_id is used as session_id.
            force_litellm_model: When set (e.g. reminder delivery), use this
                LiteLLM model id instead of reading from session state.
            on_text_chunk: Optional callback invoked with visible model text as
                it arrives from ADK events.

        Returns:
            Reply text and any files tools queued for Telegram delivery.
        """
        effective_session_id = session_id or user_id
        conversation_state = await self._get_conversation_state(
            user_id=user_id,
            session_id=effective_session_id,
        )

        request_id: int
        async with conversation_state.lock:
            conversation_state.next_request_id += 1
            request_id = conversation_state.next_request_id

            active_turn = conversation_state.active_turn
            if active_turn is not None and not active_turn.task.done():
                conversation_state.superseded_request_ids.add(active_turn.request_id)
                active_turn.task.cancel()

            task = asyncio.create_task(
                self._run_message_turn(
                    user_id=user_id,
                    message=message,
                    session_id=effective_session_id,
                    force_litellm_model=force_litellm_model,
                    on_text_chunk=on_text_chunk,
                )
            )
            conversation_state.active_turn = _ActiveTelegramTurn(
                request_id=request_id,
                task=task,
            )

        try:
            return await task
        except asyncio.CancelledError:
            was_superseded = await self._consume_superseded_request(
                conversation_state=conversation_state,
                request_id=request_id,
            )
            if was_superseded:
                return TelegramAgentReply(text="", superseded=True)
            raise
        finally:
            async with conversation_state.lock:
                active_turn = conversation_state.active_turn
                is_current_turn = (
                    active_turn is not None and active_turn.request_id == request_id
                )
                if is_current_turn:
                    conversation_state.active_turn = None

            await self._clear_conversation_state_if_idle(
                user_id=user_id,
                session_id=effective_session_id,
                conversation_state=conversation_state,
            )

    async def _run_message_turn(
        self,
        *,
        user_id: str,
        message: str,
        session_id: str,
        force_litellm_model: str | None,
        on_text_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> TelegramAgentReply:
        """Run one Telegram turn.

        This repo uses LiteLLM-backed ADK models. LiteLLM supports unary
        ``run_async()`` but not ADK live bidi ``connect()`` sessions, so the
        Telegram steering behavior is implemented as "newest message wins":
        cancel the in-flight turn, suppress its stale reply, and run the newest
        message immediately in the same ADK session.
        """
        latency_log = _telegram_latency_log_enabled()
        pipeline_start = time.perf_counter()

        session = await self.runner.session_service.get_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=session_id,
        )

        if session is None:
            session = await self.runner.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session_id,
                state={"user_id": user_id},
            )
            logger.info(f"Created new session with user_id={user_id}")
        elif "user_id" not in session.state:
            logger.info(f"Session missing user_id, recreating for user={user_id}")
            try:
                await self.runner.session_service.delete_session(
                    app_name=self.app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
            except Exception:
                logger.warning(
                    f"Could not delete session for user={user_id}, "
                    f"session={session_id}. Proceeding with recreation."
                )
            session = await self.runner.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session_id,
                state={"user_id": user_id},
            )
            logger.info(f"Recreated session with user_id={user_id}")

        logger.info(f"Session state keys: {list(session.state.keys())}")

        session_ready = time.perf_counter()
        content = types.Content(role="user", parts=[types.Part(text=message)])
        response_parts: list[str] = []
        streamed_text = False
        streamed_text_length = 0

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
        begin_telegram_file_batch()
        resolved_model = self._resolve_litellm_model_for_session_state(
            session.state,
            force_litellm_model=force_litellm_model,
        )
        try:
            async with _telegram_litellm_model_context(resolved_model):
                async for event in self.runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
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

                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, "thought") and part.thought:
                                continue
                            if part.text:
                                response_parts.append(part.text)
                        if on_text_chunk is not None:
                            full_response_text = "".join(response_parts)
                            unsent_text = full_response_text[streamed_text_length:]
                            if unsent_text.strip():
                                await on_text_chunk(unsent_text)
                                streamed_text = True
                                streamed_text_length = len(full_response_text)
        except asyncio.CancelledError as exc:
            pending_on_cancel = end_telegram_file_batch()
            discard_telegram_staging_files(pending_on_cancel)
            raise TelegramTurnSupersededError() from exc
        except Exception:
            pending_on_error = end_telegram_file_batch()
            discard_telegram_staging_files(pending_on_error)
            raise

        if latency_log and not first_stream_event_logged:
            logger.info(
                "telegram.adk_first_stream_event user_id=%s "
                "ms_after_run_async_started=n/a (run_async yielded no events)",
                user_id,
            )

        pending_files = end_telegram_file_batch()
        return TelegramAgentReply(
            text="".join(response_parts),
            documents=tuple(pending_files),
            streamed_text=streamed_text,
        )

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

        await self._cancel_active_turn(
            user_id=user_id,
            session_id=effective_session_id,
        )

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
    ) -> TelegramAgentReply:
        """Process a reminder through the ADK agent for personalized response.

        This method injects a reminder as a simulated user message, allowing
        the agent to generate a contextual, personalized response rather than
        sending a hardcoded notification.

        Args:
            user_id: Unique identifier for the user (e.g., Telegram chat ID).
            reminder_message: The stored reminder instruction to fulfill now.
            scheduled_time: When the reminder was scheduled for.
            session_id: Optional session ID for conversation continuity.
                If not provided, reminder delivery uses a dedicated reminder
                session so it does not inherit the user's scheduling chat.

        Returns:
            The agent's personalized reply and any queued file attachments.
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

        effective_session_id = session_id or self._build_reminder_session_id(user_id)
        if session_id is None:
            await self.reset_session(
                user_id=user_id,
                session_id=effective_session_id,
            )

        main_session = await self.runner.session_service.get_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=user_id,
        )
        reminder_litellm_model = self._resolve_litellm_model_for_session_state(
            main_session.state if main_session else None,
            force_litellm_model=None,
        )

        # Process through the agent using the existing message flow
        response = await self.process_message(
            user_id=user_id,
            message=prompt,
            session_id=effective_session_id,
            force_litellm_model=reminder_litellm_model,
        )

        return response

    async def process_claude_job_completion(
        self,
        user_id: str,
        *,
        job_id: str,
        cwd: str,
        result: dict[str, Any],
    ) -> TelegramAgentReply:
        """Run one agent turn with the finished Claude job output in-session.

        Uses the same ``session_id`` as normal Telegram chat (``user_id``) so the
        model sees this as the next user message after the tool started the job.

        Note:
            Like :meth:`process_message`, this cancels any in-flight Telegram turn
            if one is active when this runs (newest-wins coordination).
        """
        status = str(result.get("status") or "unknown")
        exit_raw = result.get("exit_code")
        exit_code = "n/a" if exit_raw is None else str(exit_raw)
        truncated = bool(result.get("truncated"))
        truncated_line = (
            "Note: subprocess output was truncated at the capture limit."
            if truncated
            else ""
        )
        stdout_section = str(result.get("stdout") or "").strip() or "(none)"
        stderr_section = str(result.get("stderr") or "").strip() or "(none)"
        error_message = str(result.get("message") or "").strip()
        if error_message and stdout_section == "(none)" and stderr_section == "(none)":
            stdout_section = f"(tool error) {error_message}"

        message = CLAUDE_JOB_COMPLETION_TEMPLATE.format(
            job_id=job_id,
            cwd=cwd,
            status=status,
            exit_code=exit_code,
            truncated_line=truncated_line,
            stdout_section=stdout_section,
            stderr_section=stderr_section,
        )
        logger.info(
            "Processing Claude job completion for user %s job_id=%s status=%s",
            user_id,
            job_id,
            status,
        )
        return await self.process_message(
            user_id=user_id,
            message=message,
            session_id=user_id,
            on_text_chunk=None,
        )

    def _build_reminder_session_id(self, user_id: str) -> str:
        """Return the dedicated session used for reminder delivery."""
        return f"{user_id}{REMINDER_SESSION_SUFFIX}"


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
    force_litellm_model: str | None = None,
    on_text_chunk: Callable[[str], Awaitable[None]] | None = None,
) -> TelegramAgentReply:
    """Process a message through the ADK agent.

    This function is maintained for backwards compatibility.
    Consider using the TelegramHandler class directly for new code.

    Args:
        user_id: Unique identifier for the user (e.g., Telegram chat ID).
        message: The message text to process.
        session_id: Optional session ID for conversation continuity.
            If not provided, user_id is used as session_id.
        force_litellm_model: Optional LiteLLM model id override (see TelegramHandler).
        on_text_chunk: Optional callback invoked with visible model text as it
            streams from the ADK runner.

    Returns:
        The agent's response text and optional Telegram document queue.

    Raises:
        RuntimeError: If the handler hasn't been initialized.
    """
    if _handler is None:
        raise RuntimeError("Handler not initialized. Call initialize_runner() first.")
    return await _handler.process_message(
        user_id=user_id,
        message=message,
        session_id=session_id,
        force_litellm_model=force_litellm_model,
        on_text_chunk=on_text_chunk,
    )


async def process_claude_job_completion(
    user_id: str,
    *,
    job_id: str,
    cwd: str,
    result: dict[str, Any],
) -> TelegramAgentReply | None:
    """Inject a Claude job result into the user's session and run one agent turn."""
    if _handler is None:
        return None
    return await _handler.process_claude_job_completion(
        user_id=user_id,
        job_id=job_id,
        cwd=cwd,
        result=result,
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
