"""Tests for telegram_handler module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agent.telegram_handler import (
    TelegramHandler,
    clear_session,
    initialize_runner,
    process_message,
    reset_session,
)


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

        assert response == "Hello!"

    @pytest.mark.asyncio
    async def test_process_message_uses_existing_session(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that existing session is used when available."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        # Mock existing session
        existing_session = MagicMock(id="existing-session")

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

            assert response == "Response"
            mock_get.assert_called_once()

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

        assert response == "Part 1 Part 2"

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

        assert response == "Response"

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

        assert response == "Valid"

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
        assert response == "Text"

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
        assert response == "Hello! How can I help?"
        assert "internal reasoning" not in response

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

        assert response == "Response"

    @pytest.mark.asyncio
    async def test_clear_session_returns_true(self, mock_agent: MagicMock) -> None:
        """Test that session is cleared and True is returned."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        result = await handler.clear_session("user-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_clear_session_uses_user_id_as_session_id(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that user_id is used as session_id when not provided."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        # Mock the delete_session method
        with patch.object(
            handler.runner.session_service, "delete_session", new_callable=AsyncMock
        ) as mock_delete:
            await handler.clear_session("user-456")

            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-456",
                session_id="user-456",
            )

    @pytest.mark.asyncio
    async def test_clear_session_uses_provided_session_id(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that provided session_id is used."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        # Mock the delete_session method
        with patch.object(
            handler.runner.session_service, "delete_session", new_callable=AsyncMock
        ) as mock_delete:
            await handler.clear_session("user-1", session_id="custom-session")

            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="custom-session",
            )

    @pytest.mark.asyncio
    async def test_clear_session_logs_exception_and_returns_false(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that exceptions are logged and False is returned."""
        handler = TelegramHandler(mock_agent, app_name="test-app")

        with (
            patch.object(
                handler.runner.session_service,
                "delete_session",
                new_callable=AsyncMock,
                side_effect=Exception("Session not found"),
            ),
            patch("agent.telegram_handler.logger") as mock_logger,
        ):
            result = await handler.clear_session("user-1")

            assert result is False
            mock_logger.exception.assert_called_once()

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
                "delete_session",
                new_callable=AsyncMock,
                side_effect=Exception("Delete failed"),
            ),
            patch("agent.telegram_handler.logger") as mock_logger,
        ):
            result = await handler.reset_session("user-1")

            assert result is False
            mock_logger.exception.assert_called_once()


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
        from agent import telegram_handler

        telegram_handler._handler = None

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
        from agent import telegram_handler

        assert telegram_handler._handler is not None
        with patch.object(
            telegram_handler._handler.runner, "run_async", mock_run_async
        ):
            response = await process_message("user-1", "Hello")

        assert response == "Response"


class TestClearSessionFunction:
    """Tests for module-level clear_session function (backwards compatibility)."""

    @pytest.mark.asyncio
    async def test_returns_false_when_handler_not_initialized(self) -> None:
        """Test that False is returned when handler not initialized."""
        from agent import telegram_handler

        telegram_handler._handler = None

        result = await clear_session("user-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_delegates_to_handler(self, mock_agent: MagicMock) -> None:
        """Test that function delegates to handler instance."""
        initialize_runner(mock_agent, app_name="test-app")

        result = await clear_session("user-1")

        assert result is True


class TestResetSessionFunction:
    """Tests for module-level reset_session function (backwards compatibility)."""

    @pytest.mark.asyncio
    async def test_returns_false_when_handler_not_initialized(self) -> None:
        """Test that False is returned when handler not initialized."""
        from agent import telegram_handler

        telegram_handler._handler = None

        result = await reset_session("user-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_delegates_to_handler(self, mock_agent: MagicMock) -> None:
        """Test that function delegates to handler instance."""
        initialize_runner(mock_agent, app_name="test-app")

        result = await reset_session("user-1")

        assert result is True
