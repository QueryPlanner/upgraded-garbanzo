"""Tests for telegram_handler module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agent.telegram_handler import (
    clear_session,
    initialize_runner,
    process_message,
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


class TestInitializeRunner:
    """Tests for initialize_runner function."""

    def test_initializes_runner_with_agent(self, mock_agent: MagicMock) -> None:
        """Test that runner is initialized with the provided agent."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        assert runner is not None
        assert isinstance(runner, InMemoryRunner)

    def test_uses_default_app_name(self, mock_agent: MagicMock) -> None:
        """Test that default app name is used when not provided."""
        runner = initialize_runner(mock_agent)

        assert runner.app_name == "telegram-bot"


class TestProcessMessage:
    """Tests for process_message function."""

    @pytest.mark.asyncio
    async def test_raises_error_when_runner_not_initialized(self) -> None:
        """Test that RuntimeError is raised when runner not initialized."""
        # Reset the global runner
        from agent import telegram_handler

        telegram_handler._runner = None

        with pytest.raises(RuntimeError, match="Runner not initialized"):
            await process_message("user-1", "Hello")

    @pytest.mark.asyncio
    async def test_creates_new_session_when_not_exists(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that new session is created when one doesn't exist."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        # Mock the runner's run_async to return a response
        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Hello!")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        assert response == "Hello!"

    @pytest.mark.asyncio
    async def test_uses_existing_session(self, mock_agent: MagicMock) -> None:
        """Test that existing session is used when available."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        # Mock existing session
        existing_session = MagicMock(id="existing-session")

        with patch.object(
            runner.session_service, "get_session", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = existing_session

            async def mock_run_async(**kwargs: object) -> object:
                yield MagicMock(
                    content=types.Content(
                        role="model", parts=[types.Part(text="Response")]
                    )
                )

            with patch.object(runner, "run_async", mock_run_async):
                response = await process_message(
                    "user-1", "Hello", session_id="existing-session"
                )

            assert response == "Response"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_concatenates_multiple_response_parts(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that multiple response parts are concatenated."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Part 1 ")])
            )
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Part 2")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        assert response == "Part 1 Part 2"

    @pytest.mark.asyncio
    async def test_uses_user_id_as_session_id(self, mock_agent: MagicMock) -> None:
        """Test that user_id is used as session_id when not provided."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        captured_session_id: str | None = None

        async def mock_run_async(
            user_id: str, session_id: str, **kwargs: object
        ) -> object:
            nonlocal captured_session_id
            captured_session_id = session_id
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Hi")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            await process_message("user-123", "Hello")

        assert captured_session_id == "user-123"

    @pytest.mark.asyncio
    async def test_handles_event_without_content(self, mock_agent: MagicMock) -> None:
        """Test that events without content are handled gracefully."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Event without content
            yield MagicMock(content=None)
            # Event with content that has response
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Response")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        assert response == "Response"

    @pytest.mark.asyncio
    async def test_handles_event_without_parts(self, mock_agent: MagicMock) -> None:
        """Test that events with content but no parts are handled."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Event with content but empty parts
            yield MagicMock(content=types.Content(role="model", parts=[]))
            # Event with parts that have text
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Valid")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        assert response == "Valid"

    @pytest.mark.asyncio
    async def test_handles_part_without_text(self, mock_agent: MagicMock) -> None:
        """Test that parts without text are skipped."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Event with parts list containing a Part with text=""
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="")])
            )
            # Event with valid text part
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Text")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        # Empty string is falsy but still concatenated
        assert response == "Text"

    @pytest.mark.asyncio
    async def test_filters_thought_parts(self, mock_agent: MagicMock) -> None:
        """Test that thought parts (internal reasoning) are filtered out."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Create a thought part (internal reasoning)
            thought_part = types.Part(text="This is internal reasoning...")
            # Manually set thought attribute since Part constructor doesn't have it
            object.__setattr__(thought_part, "thought", True)

            # Create a regular response part
            response_part = types.Part(text="Hello! How can I help?")

            # Yield event with both parts
            yield MagicMock(
                content=types.Content(
                    role="model", parts=[thought_part, response_part]
                )
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        # Only the non-thought part should be in the response
        assert response == "Hello! How can I help?"
        assert "internal reasoning" not in response

    @pytest.mark.asyncio
    async def test_handles_part_without_thought_attribute(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that parts without thought attribute are handled."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        async def mock_run_async(**kwargs: object) -> object:
            # Regular part without thought attribute
            yield MagicMock(
                content=types.Content(role="model", parts=[types.Part(text="Response")])
            )

        with patch.object(runner, "run_async", mock_run_async):
            response = await process_message("user-1", "Hello")

        assert response == "Response"


class TestClearSession:
    """Tests for clear_session function."""

    @pytest.mark.asyncio
    async def test_returns_false_when_runner_not_initialized(self) -> None:
        """Test that False is returned when runner not initialized."""
        from agent import telegram_handler

        telegram_handler._runner = None

        result = await clear_session("user-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_clears_session_and_returns_true(self, mock_agent: MagicMock) -> None:
        """Test that session is cleared and True is returned."""
        initialize_runner(mock_agent, app_name="test-app")

        result = await clear_session("user-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_uses_user_id_as_session_id_when_not_provided(
        self, mock_agent: MagicMock
    ) -> None:
        """Test that user_id is used as session_id when not provided."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        # Mock the delete_session method
        with patch.object(
            runner.session_service, "delete_session", new_callable=AsyncMock
        ) as mock_delete:
            await clear_session("user-456")

            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-456",
                session_id="user-456",
            )

    @pytest.mark.asyncio
    async def test_uses_provided_session_id(self, mock_agent: MagicMock) -> None:
        """Test that provided session_id is used."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        # Mock the delete_session method
        with patch.object(
            runner.session_service, "delete_session", new_callable=AsyncMock
        ) as mock_delete:
            await clear_session("user-1", session_id="custom-session")

            mock_delete.assert_called_once_with(
                app_name="test-app",
                user_id="user-1",
                session_id="custom-session",
            )

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, mock_agent: MagicMock) -> None:
        """Test that False is returned when exception occurs."""
        runner = initialize_runner(mock_agent, app_name="test-app")

        with patch.object(
            runner.session_service,
            "delete_session",
            new_callable=AsyncMock,
            side_effect=Exception("Session not found"),
        ):
            result = await clear_session("user-1")

            assert result is False
