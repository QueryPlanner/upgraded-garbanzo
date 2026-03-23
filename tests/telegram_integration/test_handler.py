"""Tests for telegram_handler module."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import NoReturn
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agent.telegram.handler import (
    REMINDER_PROMPT_TEMPLATE,
    REMINDER_SESSION_SUFFIX,
    TelegramAgentReply,
    TelegramHandler,
    _read_litellm_model_from_state,
    _telegram_litellm_model_context,
    get_handler,
    initialize_runner,
    process_message,
    reset_session,
)
from agent.utils.app_timezone import format_stored_instant_for_display


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock LlmAgent."""
    agent = MagicMock(spec=LlmAgent)
    agent.name = "test_agent"
    return agent


@pytest.fixture
def mock_runner() -> MagicMock:
    """Create a mock InMemoryRunner."""
    runner = MagicMock(spec=InMemoryRunner)
    runner.app_name = "test-app"
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock(
        return_value=MagicMock(id="test-session")
    )
    runner.session_service.delete_session = AsyncMock()
    return runner


class TestTelegramHandler:
    """Tests for TelegramHandler class."""

    def test_initializes_with_agent(self, mock_agent: MagicMock) -> None:
        """Test that handler is initialized with the provided agent."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        assert handler.agent is mock_agent
        assert handler.app_name == "test-app"
        assert handler.runner is not None
        assert isinstance(handler.runner, InMemoryRunner)

    def test_uses_default_app_name(self, mock_agent: MagicMock) -> None:
        """Test that default app name is used when not provided."""
        handler = TelegramHandler(mock_agent)

        assert handler.app_name == "telegram-bot"

    @pytest.mark.asyncio
    async def test_process_message_creates_new_session(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that new session is created when one doesn't exist."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        # Mock the runner's run_async to return a response
        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Hello!")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        assert response.text == "Hello!"

    @pytest.mark.asyncio
    async def test_process_message_logs_pre_llm_latency_when_enabled(
        self,
        mock_agent: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """TELEGRAM_LATENCY_LOG=1 emits structured pre-LLM timing at INFO."""
        monkeypatch.setenv("TELEGRAM_LATENCY_LOG", "1")
        caplog.set_level(logging.INFO, logger="agent.telegram.handler")

        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Hello!")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            await handler.process_message("user-1", "Hello")

        messages = [record.message for record in caplog.records]
        assert any("telegram.pre_llm_latency" in m for m in messages)
        assert any("telegram.adk_first_stream_event" in m for m in messages)

    @pytest.mark.asyncio
    async def test_process_message_discards_pending_files_when_run_async_fails(
        self, mock_agent: MagicMock
    ) -> None:
        """On stream failure, end batch and discard staged uploads before re-raise."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        class _StreamFails:
            def __aiter__(self) -> "_StreamFails":
                return self

            async def __anext__(self) -> NoReturn:
                raise RuntimeError("stream failed")

        def mock_run_async(**kwargs: object) -> _StreamFails:
            return _StreamFails()

        with (
            patch.object(handler.runner, "run_async", mock_run_async),
            patch(
                "agent.telegram.handler.discard_telegram_staging_files",
            ) as mock_discard,
            pytest.raises(RuntimeError, match="stream failed"),
        ):
            await handler.process_message("user-1", "Hello")

        mock_discard.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_process_message_uses_existing_session(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that existing session is used when available."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        # Mock existing session with user_id in state
        existing_session = MagicMock(id="existing-session")
        existing_session.state = {"user_id": "user-1"}

        with patch.object(
            handler.runner.session_service, "get_session", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = existing_session

            async def mock_run_async(**kwargs: object) -> object:
                yield MagicMock(
                    content=types.Content(
                        role="model", parts=[types.Part(text="Response")]
                    )
                )

            with patch.object(handler.runner, "run_async", mock_run_async):
                response = await handler.process_message(
                    "user-1", "Hello", session_id="existing-session"
                )

            assert response.text == "Response"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_recreates_session_missing_user_id(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that existing session missing user_id in state gets recreated."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        # Mock existing session without user_id in state
        existing_session = MagicMock()
        existing_session.state = {}  # Missing user_id

        # Mock recreated session with user_id in state
        recreated_session = MagicMock()
        recreated_session.state = {"user_id": "user-1"}

        with (
            patch.object(
                handler.runner.session_service, "get_session", new_callable=AsyncMock
            ) as mock_get,
            patch.object(
                handler.runner.session_service, "delete_session", new_callable=AsyncMock
            ) as mock_delete,
            patch.object(
                handler.runner.session_service, "create_session", new_callable=AsyncMock
            ) as mock_create,
        ):
            mock_get.return_value = existing_session
            mock_create.return_value = recreated_session

            async def mock_run_async(**kwargs: object) -> object:
                yield MagicMock(
                    content=types.Content(
                        role="model", parts=[types.Part(text="Response")]
                    )
                )

            with patch.object(handler.runner, "run_async", mock_run_async):
                response = await handler.process_message("user-1", "Hello")

            assert response.text == "Response"
            mock_get.assert_called_once()
            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="user-1",
            )
            mock_create.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="user-1",
                state={"user_id": "user-1"},
            )

    @pytest.mark.asyncio
    async def test_process_message_concatenates_multiple_parts(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that multiple response parts are concatenated."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Part 1 ")])
            )
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Part 2")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        assert response.text == "Part 1 Part 2"

    @pytest.mark.asyncio
    async def test_process_message_uses_user_id_as_session_id(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that user_id is used as session_id when not provided."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        captured_session_id: str | None = None

        async def mock_run_async(
            user_id: str, session_id: str, **kwargs: object
        ) -> object:
            nonlocal captured_session_id
            captured_session_id = session_id
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Hi")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            await handler.process_message("user-123", "Hello")

        assert captured_session_id == "user-123"

    @pytest.mark.asyncio
    async def test_process_message_handles_event_without_content(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that events without content are handled gracefully."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Event without content
            yield MagicMock(content=None)
            # Event with content that has response
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Response")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        assert response.text == "Response"

    @pytest.mark.asyncio
    async def test_process_message_handles_event_without_parts(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that events with content but no parts are handled."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Event with content but empty parts
            yield MagicMock(content=types.Content(role="model", parts=[]))
            # Event with parts that have text
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Valid")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        assert response.text == "Valid"

    @pytest.mark.asyncio
    async def test_process_message_handles_part_without_text(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that parts without text are skipped."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Event with parts list containing a Part with text=""
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="")])
            )
            # Event with valid text part
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Text")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        # Empty string is falsy but still concatenated
        assert response.text == "Text"

    @pytest.mark.asyncio
    async def test_process_message_filters_thought_parts(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that thought parts (internal reasoning) are filtered out."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Create a thought part (internal reasoning)
            thought_part = types.Part(text="This is internal reasoning...")
            # Manually set thought attribute since Part constructor doesn't have it
            object.__setattr__(thought_part, "thought", True)

            # Create a regular response part
            response_part = types.Part(text="Hello! How can I help?")

            # Yield event with both parts
            yield MagicMock(
                content=types.Content(role="model", parts=[thought_part, response_part])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        # Only the non-thought part should be in the response
        assert response.text == "Hello! How can I help?"
        assert "internal reasoning" not in response.text

    @pytest.mark.asyncio
    async def test_process_message_handles_part_without_thought_attribute(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that parts without thought attribute are handled."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Regular part without thought attribute
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Response")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_message("user-1", "Hello")

        assert response.text == "Response"

    @pytest.mark.asyncio
    async def test_process_message_supersedes_inflight_turn(
        self, mock_agent: MagicMock
    ) -> None:
        """A newer Telegram message cancels the stale in-flight turn."""
        handler = TelegramHandler(mock_agent, app_name="test-app")
        first_turn_started = asyncio.Event()

        async def mock_run_async(
            *,
            new_message: types.Content,
            **kwargs: object,
        ) -> object:
            assert new_message.parts is not None
            prompt = new_message.parts[0].text
            if prompt == "first":
                first_turn_started.set()
                await asyncio.Future()

            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="newest")])
            )

        with (
            patch.object(handler.runner, "run_async", mock_run_async),
            patch(
                "agent.telegram.handler.discard_telegram_staging_files"
            ) as mock_discard,
        ):
            first_task = asyncio.create_task(handler.process_message("user-1", "first"))
            await first_turn_started.wait()

            second_reply = await handler.process_message(
                "user-1",
                "stop and answer briefly",
            )
            first_reply = await first_task

        assert first_reply.superseded is True
        assert first_reply.text == ""
        assert second_reply.text == "newest"
        mock_discard.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_process_message_reraises_external_cancellation(
        self, mock_agent: MagicMock
    ) -> None:
        """External cancellation should propagate when no newer turn superseded it."""
        handler = TelegramHandler(mock_agent, app_name="test-app")
        run_started = asyncio.Event()

        async def mock_run_async(**kwargs: object) -> object:
            run_started.set()
            await asyncio.Future()
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="unused")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            task = asyncio.create_task(handler.process_message("user-1", "first"))
            await run_started.wait()
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_reset_session_cancels_inflight_turn(
        self, mock_agent: MagicMock
    ) -> None:
        """Reset should cancel the stale turn before recreating the session."""
        handler = TelegramHandler(mock_agent, app_name="test-app")
        run_started = asyncio.Event()

        async def mock_run_async(**kwargs: object) -> object:
            run_started.set()
            await asyncio.Future()
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="unused")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            first_task = asyncio.create_task(handler.process_message("user-1", "first"))
            await run_started.wait()

            reset_result = await handler.reset_session("user-1")
            first_reply = await first_task

        assert reset_result is True
        assert first_reply.superseded is True

    @pytest.mark.asyncio
    async def test_cancel_active_turn_handles_plain_cancelled_error(
        self, mock_agent: MagicMock
    ) -> None:
        """The reset helper should also tolerate plain task cancellation."""
        import agent.telegram.handler as handler_module

        handler = TelegramHandler(mock_agent, app_name="test-app")
        conversation_state = await handler._get_conversation_state("user-1", "user-1")

        async def never_finish() -> TelegramAgentReply:
            await asyncio.Future()
            raise AssertionError("unreachable")

        active_task = asyncio.create_task(never_finish())
        async with conversation_state.lock:
            conversation_state.next_request_id = 1
            conversation_state.active_turn = handler_module._ActiveTelegramTurn(
                request_id=1,
                task=active_task,
            )

        await handler._cancel_active_turn("user-1", "user-1")

        assert active_task.cancelled() is True

    @pytest.mark.asyncio
    async def test_cancel_active_turn_handles_superseded_error(
        self, mock_agent: MagicMock
    ) -> None:
        """The reset helper should swallow the custom superseded cancellation."""
        import agent.telegram.handler as handler_module

        handler = TelegramHandler(mock_agent, app_name="test-app")
        conversation_state = await handler._get_conversation_state("user-1", "user-1")

        async def raise_superseded() -> TelegramAgentReply:
            try:
                await asyncio.Future()
            except asyncio.CancelledError as exc:
                raise handler_module.TelegramTurnSupersededError() from exc
            raise AssertionError("unreachable")

        active_task = asyncio.create_task(raise_superseded())
        async with conversation_state.lock:
            conversation_state.next_request_id = 1
            conversation_state.active_turn = handler_module._ActiveTelegramTurn(
                request_id=1,
                task=active_task,
            )

        await handler._cancel_active_turn("user-1", "user-1")

        assert active_task.done() is True

    @pytest.mark.asyncio
    async def test_reset_session_deletes_and_creates_new(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that reset_session deletes old and creates new session."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        with (
            patch.object(
                handler.runner.session_service, "delete_session", new_callable=AsyncMock
            ) as mock_delete,
            patch.object(
                handler.runner.session_service, "create_session", new_callable=AsyncMock
            ) as mock_create,
        ):
            result = await handler.reset_session("user-1")

            assert result is True
            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="user-1",
            )
            mock_create.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="user-1",
                state={"user_id": "user-1"},
            )

    @pytest.mark.asyncio
    async def test_reset_session_uses_provided_session_id(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that reset_session uses provided session_id."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        with (
            patch.object(
                handler.runner.session_service, "delete_session", new_callable=AsyncMock
            ) as mock_delete,
            patch.object(
                handler.runner.session_service, "create_session", new_callable=AsyncMock
            ) as mock_create,
        ):
            result = await handler.reset_session("user-1", session_id="custom-session")

            assert result is True
            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="custom-session",
            )
            mock_create.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="custom-session",
                state={"user_id": "user-1"},
            )

    @pytest.mark.asyncio
    async def test_reset_session_logs_exception_and_returns_false(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that reset_session logs exceptions and returns False."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        with (
            patch.object(
                handler.runner.session_service,
                "create_session",
                new_callable=AsyncMock,
                side_effect=Exception("Create failed"),
            ),
            patch("agent.telegram.handler.logger") as mock_logger,
        ):
            result = await handler.reset_session("user-1")

            assert result is False
            mock_logger.exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_session_succeeds_when_delete_fails(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that reset_session succeeds even if delete_session fails."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        with (
            patch.object(
                handler.runner.session_service,
                "delete_session",
                new_callable=AsyncMock,
                side_effect=Exception("Session not found"),
            ),
            patch.object(
                handler.runner.session_service,
                "create_session",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("agent.telegram.handler.logger") as mock_logger,
        ):
            result = await handler.reset_session("user-1")

            assert result is True
            mock_create.assert_called_once()
            # Should have logged a warning for the delete failure
            mock_logger.warning.assert_called_once()


class TestInitializeRunner:
    """Tests for initialize_runner function (backwards compatibility)."""

    def test_initializes_runner_with_agent(self, mock_agent: MagicMock) -> None:
        """Test that runner is initialized with the provided agent."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        assert runner is not None
        assert isinstance(runner, InMemoryRunner)

    def test_uses_default_app_name(self, mock_agent: MagicMock) -> None:
        """Test that default app name is used when not provided."""
        runner = initialize_runner(mock_agent)

        assert runner.app_name == "telegram-bot"


class TestProcessMessageFunction:
    """Tests for module-level process_message function (backwards compatibility)."""

    @pytest.mark.asyncio
    async def test_raises_error_when_handler_not_initialized(self) -> None:
        """Test that RuntimeError is raised when handler not initialized."""
        # Reset the global handler
        from agent.telegram import handler

        handler._handler = None

        with pytest.raises(RuntimeError, match="Handler not initialized"):
            await process_message("user-1", "Hello")

    @pytest.mark.asyncio
    async def test_delegates_to_handler(self, mock_agent: MagicMock) -> None:
        """Test that function delegates to handler instance."""
        initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Response")])
            )

        # Get the handler created by initialize_runner
        from agent.telegram import handler

        assert handler._handler is not None
        with patch.object(handler._handler.runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        assert response.text == "Response"


class TestResetSessionFunction:
    """Tests for module-level reset_session function (backwards compatibility)."""

    @pytest.mark.asyncio
    async def test_returns_false_when_handler_not_initialized(self) -> None:
        """Test that False is returned when handler not initialized."""
        from agent.telegram import handler

        handler._handler = None

        result = await reset_session("user-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_delegates_to_handler(self, mock_agent: MagicMock) -> None:
        """Test that function delegates to handler instance."""
        initialize_runner(mock_agent, app_name="test-app")

        with patch(
            "agent.telegram.handler.TelegramHandler.reset_session",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_handler_reset:
            result = await reset_session("user-1", session_id="custom-session")

            assert result is True
            mock_handler_reset.assert_called_once_with(
                user_id="user-1", session_id="custom-session"
            )


class TestProcessReminder:
    """Tests for process_reminder method."""

    @pytest.mark.asyncio
    async def test_processes_reminder_through_agent(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that reminder is processed through the agent."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="Hey! Don't forget about lunch!")],
                )
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            response = await handler.process_reminder(
                user_id="user-1",
                reminder_message="lunch",
                scheduled_time=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
            )

        assert "lunch" in response.text or "Hey!" in response.text

    @pytest.mark.asyncio
    async def test_formats_reminder_prompt_correctly(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that reminder prompt is formatted with correct information."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        captured_message: str | None = None

        async def mock_run_async(
            user_id: str, session_id: str, new_message: types.Content, **kwargs: object
        ) -> object:
            nonlocal captured_message
            if new_message.parts:
                captured_message = new_message.parts[0].text
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Response")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            await handler.process_reminder(
                user_id="user-1",
                reminder_message="take a break",
                scheduled_time=datetime(2026, 3, 19, 15, 30, tzinfo=UTC),
            )

        assert captured_message is not None
        assert "take a break" in captured_message
        expected_local = format_stored_instant_for_display(
            datetime(2026, 3, 19, 15, 30, tzinfo=UTC).isoformat(timespec="seconds")
        )
        assert expected_local in captured_message
        assert "[SCHEDULED REMINDER]" in captured_message
        assert "Do not call tools." in captured_message

    @pytest.mark.asyncio
    async def test_uses_dedicated_session_id(self, mock_agent: MagicMock) -> None:
        """Test that reminder delivery uses a dedicated reminder session."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        captured_session_id: str | None = None

        async def mock_run_async(
            user_id: str, session_id: str, **kwargs: object
        ) -> object:
            nonlocal captured_session_id
            captured_session_id = session_id
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="OK")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            await handler.process_reminder(
                user_id="user-42",
                reminder_message="test",
                scheduled_time=datetime.now(UTC),
            )

        assert captured_session_id == f"user-42{REMINDER_SESSION_SUFFIX}"

    @pytest.mark.asyncio
    async def test_resets_dedicated_reminder_session(
        self, mock_agent: MagicMock
    ) -> None:
        """Test reminder delivery starts from a clean reminder-only session."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="OK")])
            )

        with (
            patch.object(
                handler,
                "reset_session",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_reset,
            patch.object(handler.runner, "run_async", mock_run_async),
        ):
            await handler.process_reminder(
                user_id="user-42",
                reminder_message="test",
                scheduled_time=datetime.now(UTC),
            )

        mock_reset.assert_called_once_with(
            user_id="user-42",
            session_id=f"user-42{REMINDER_SESSION_SUFFIX}",
        )

    @pytest.mark.asyncio
    async def test_uses_custom_session_id_when_provided(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that custom session_id is used when provided."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        captured_session_id: str | None = None

        async def mock_run_async(
            user_id: str, session_id: str, **kwargs: object
        ) -> object:
            nonlocal captured_session_id
            captured_session_id = session_id
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="OK")])
            )

        with patch.object(handler.runner, "run_async", mock_run_async):
            await handler.process_reminder(
                user_id="user-42",
                reminder_message="test",
                scheduled_time=datetime.now(UTC),
                session_id="custom-session",
            )

        assert captured_session_id == "custom-session"


class TestGetHandler:
    """Tests for get_handler function."""

    def test_returns_none_when_not_initialized(self) -> None:
        """Test that None is returned when handler not initialized."""
        from agent.telegram import handler

        handler._handler = None

        result = get_handler()

        assert result is None

    def test_returns_handler_when_initialized(self, mock_agent: MagicMock) -> None:
        """Test that handler is returned when initialized."""
        initialize_runner(mock_agent, app_name="test-app")

        result = get_handler()

        assert result is not None
        assert isinstance(result, TelegramHandler)


class TestTelegramLitellmSessionHelpers:
    """Session model resolution and context var behavior."""

    def test_read_litellm_model_strips_and_rejects_blank(self) -> None:
        assert _read_litellm_model_from_state({"telegram_litellm_model": "  "}) is None
        assert (
            _read_litellm_model_from_state({"telegram_litellm_model": " openai/x "})
            == "openai/x"
        )

    @pytest.mark.asyncio
    async def test_litellm_model_context_restores_previous_value(self) -> None:
        from agent.litellm_session_router import CURRENT_TELEGRAM_LITELLM_MODEL

        outer = CURRENT_TELEGRAM_LITELLM_MODEL.set("prev")
        try:
            async with _telegram_litellm_model_context("during"):
                assert CURRENT_TELEGRAM_LITELLM_MODEL.get() == "during"
            assert CURRENT_TELEGRAM_LITELLM_MODEL.get() == "prev"
        finally:
            CURRENT_TELEGRAM_LITELLM_MODEL.reset(outer)

    def test_resolve_litellm_model_prefers_force_over_state(
        self, mock_agent: MagicMock
    ) -> None:
        handler = TelegramHandler(mock_agent, app_name="test-app")
        assert (
            handler._resolve_litellm_model_for_session_state(
                {"telegram_litellm_model": "openai/glm-5"},
                force_litellm_model="openai/glm-4.7",
            )
            == "openai/glm-4.7"
        )

    def test_resolve_litellm_model_reads_session_state(
        self, mock_agent: MagicMock
    ) -> None:
        handler = TelegramHandler(mock_agent, app_name="test-app")
        assert (
            handler._resolve_litellm_model_for_session_state(
                {"telegram_litellm_model": "openai/glm-5"},
                force_litellm_model=None,
            )
            == "openai/glm-5"
        )

    def test_resolve_litellm_model_env_fallback(
        self, mock_agent: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ROOT_AGENT_MODEL", raising=False)
        handler = TelegramHandler(mock_agent, app_name="test-app")
        assert (
            handler._resolve_litellm_model_for_session_state(
                {},
                force_litellm_model=None,
            )
            == "gemini-2.5-flash"
        )

    @pytest.mark.asyncio
    async def test_process_reminder_passes_main_chat_model_as_force(
        self, mock_agent: MagicMock
    ) -> None:
        handler = TelegramHandler(mock_agent, app_name="test-app")
        main_sess = MagicMock()
        main_sess.state = {"telegram_litellm_model": "openai/glm-5"}

        mock_pm = AsyncMock(return_value=TelegramAgentReply(text="ok"))

        with (
            patch.object(
                handler.runner.session_service,
                "get_session",
                new_callable=AsyncMock,
                return_value=main_sess,
            ),
            patch.object(handler, "process_message", mock_pm),
        ):
            await handler.process_reminder(
                user_id="user-1",
                reminder_message="ping",
                scheduled_time=datetime.now(UTC),
            )

        mock_pm.assert_called_once()
        assert mock_pm.call_args.kwargs["force_litellm_model"] == "openai/glm-5"


class TestReminderPromptTemplate:
    """Tests for the reminder prompt template."""

    def test_template_contains_placeholder(self) -> None:
        """Test that template contains required placeholders."""
        assert "{reminder_message}" in REMINDER_PROMPT_TEMPLATE
        assert "{scheduled_time}" in REMINDER_PROMPT_TEMPLATE
        assert "Do not call tools." in REMINDER_PROMPT_TEMPLATE
        assert "already been scheduled and is firing now" in REMINDER_PROMPT_TEMPLATE

    def test_template_formats_correctly(self) -> None:
        """Test that template can be formatted without errors."""
        result = REMINDER_PROMPT_TEMPLATE.format(
            reminder_message="Test reminder",
            scheduled_time="2026-03-19 12:00 UTC",
        )

        assert "Test reminder" in result
        assert "2026-03-19 12:00 UTC" in result
        assert "[SCHEDULED REMINDER]" in result
