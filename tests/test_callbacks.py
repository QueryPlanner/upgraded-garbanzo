"""Unit tests for the callbacks module."""

import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import MockMemoryCallbackContext, MockState, MockToolContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool

from agent.callbacks import add_session_to_memory, notify_tool_call


def as_callback_context(context: MockMemoryCallbackContext) -> CallbackContext:
    """Treat mock callback contexts as real CallbackContext objects for typing."""
    return cast(CallbackContext, context)


class TestAddSessionToMemory:
    """Tests for the add_session_to_memory callback function."""

    @pytest.mark.asyncio
    async def test_add_session_to_memory_success(
        self,
        mock_memory_callback_context: MockMemoryCallbackContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that callback succeeds when context.add_session_to_memory succeeds."""
        caplog.set_level(logging.INFO)

        # Execute callback
        await add_session_to_memory(as_callback_context(mock_memory_callback_context))

        # Verify add_session_to_memory was called on the context
        assert mock_memory_callback_context.add_session_to_memory_called

        # Verify logging
        assert "*** Starting add_session_to_memory callback ***" in caplog.text

    @pytest.mark.asyncio
    async def test_add_session_to_memory_handles_value_error(
        self,
        mock_memory_callback_context_no_service: MockMemoryCallbackContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that callback handles ValueError (e.g., no memory service)."""
        caplog.set_level(logging.WARNING)

        # Execute callback - should not raise
        await add_session_to_memory(
            as_callback_context(mock_memory_callback_context_no_service)
        )

        # Verify the method was attempted
        assert mock_memory_callback_context_no_service.add_session_to_memory_called

        # Verify warning was logged
        assert (
            "Cannot add session to memory: memory service is not available."
            in caplog.text
        )

    @pytest.mark.asyncio
    async def test_add_session_to_memory_handles_attribute_error(
        self,
        mock_memory_callback_context_with_attribute_error: MockMemoryCallbackContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that callback handles AttributeError gracefully."""
        caplog.set_level(logging.WARNING)

        # Execute callback - should not raise
        await add_session_to_memory(
            as_callback_context(mock_memory_callback_context_with_attribute_error)
        )

        # Verify the method was attempted
        ctx = mock_memory_callback_context_with_attribute_error
        assert ctx.add_session_to_memory_called

        # Verify warning was logged with exception details
        assert "Failed to add session to memory" in caplog.text
        assert "AttributeError" in caplog.text

    @pytest.mark.asyncio
    async def test_add_session_to_memory_handles_runtime_error(
        self,
        mock_memory_callback_context_with_runtime_error: MockMemoryCallbackContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that callback handles RuntimeError gracefully."""
        caplog.set_level(logging.WARNING)

        # Execute callback - should not raise
        await add_session_to_memory(
            as_callback_context(mock_memory_callback_context_with_runtime_error)
        )

        # Verify the method was attempted
        ctx = mock_memory_callback_context_with_runtime_error
        assert ctx.add_session_to_memory_called

        # Verify warning was logged with exception details
        assert "Failed to add session to memory" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "Memory service connection failed" in caplog.text

    @pytest.mark.asyncio
    async def test_add_session_to_memory_logging_levels(
        self,
        mock_memory_callback_context: MockMemoryCallbackContext,
        mock_memory_callback_context_no_service: MockMemoryCallbackContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that callback uses appropriate logging levels."""
        # Test case 1: Success (INFO level)
        caplog.set_level(logging.INFO)
        caplog.clear()

        await add_session_to_memory(as_callback_context(mock_memory_callback_context))

        # Check for INFO log (starting callback)
        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_records) == 1
        assert "Starting add_session_to_memory" in info_records[0].message

        # Test case 2: ValueError (WARNING level)
        caplog.set_level(logging.WARNING)
        caplog.clear()

        await add_session_to_memory(
            as_callback_context(mock_memory_callback_context_no_service)
        )

        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert (
            "Cannot add session to memory: memory service is not available."
            in warning_records[0].message
        )

    @pytest.mark.asyncio
    async def test_add_session_to_memory_returns_none(
        self,
        mock_memory_callback_context: MockMemoryCallbackContext,
    ) -> None:
        """Test that callback always returns None."""
        await add_session_to_memory(as_callback_context(mock_memory_callback_context))

    @pytest.mark.asyncio
    async def test_add_session_to_memory_multiple_calls(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that callback can be called multiple times."""
        from conftest import MockMemoryCallbackContext

        caplog.set_level(logging.INFO)

        # Create multiple contexts
        ctx1 = MockMemoryCallbackContext()
        ctx2 = MockMemoryCallbackContext()

        # Execute callbacks
        await add_session_to_memory(as_callback_context(ctx1))
        await add_session_to_memory(as_callback_context(ctx2))

        # Verify both completed successfully
        assert ctx1.add_session_to_memory_called
        assert ctx2.add_session_to_memory_called

        # Verify both were logged
        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_records) == 2


def as_tool_context(context: MockToolContext) -> ToolContext:
    """Treat mock tool contexts as real ToolContext objects for typing."""
    return cast(ToolContext, context)


def make_mock_tool(name: str = "test_tool") -> BaseTool:
    """Create a mock BaseTool with the given name."""
    mock_tool = MagicMock(spec=BaseTool)
    mock_tool.name = name
    return cast(BaseTool, mock_tool)


class TestNotifyToolCall:
    """Tests for the notify_tool_call callback function."""

    @pytest.mark.asyncio
    async def test_notify_tool_call_sends_notification(self) -> None:
        """Test that notification is sent when user_id is in state."""
        mock_tool = make_mock_tool(name="schedule_reminder")
        mock_state = MockState({"user_id": "123456"})
        mock_context = MockToolContext(state=mock_state)

        mock_service = MagicMock()
        mock_service.notify_tool_call = AsyncMock()

        with patch(
            "agent.telegram.notifications.get_notification_service",
            return_value=mock_service,
        ):
            await notify_tool_call(
                tool=mock_tool,
                args={"message": "test", "time": "2024-01-01"},
                tool_context=as_tool_context(mock_context),
            )

        mock_service.notify_tool_call.assert_called_once_with(
            chat_id="123456",
            tool_name="schedule_reminder",
            args={"message": "test", "time": "2024-01-01"},
        )

    @pytest.mark.asyncio
    async def test_notify_tool_call_skips_when_no_user_id(self) -> None:
        """Test that notification is skipped when user_id is not in state."""
        mock_tool = make_mock_tool(name="test_tool")
        mock_state = MockState({})  # Empty state, no user_id
        mock_context = MockToolContext(state=mock_state)

        mock_service = MagicMock()
        mock_service.notify_tool_call = AsyncMock()

        with patch(
            "agent.telegram.notifications.get_notification_service",
            return_value=mock_service,
        ):
            await notify_tool_call(
                tool=mock_tool,
                args={"key": "value"},
                tool_context=as_tool_context(mock_context),
            )

        mock_service.notify_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_tool_call_handles_exception(self) -> None:
        """Test that exceptions are caught and logged."""
        mock_tool = make_mock_tool(name="test_tool")
        mock_state = MockState({"user_id": "123456"})
        mock_context = MockToolContext(state=mock_state)

        mock_service = MagicMock()
        mock_service.notify_tool_call = AsyncMock(
            side_effect=Exception("Telegram error")
        )

        with patch(
            "agent.telegram.notifications.get_notification_service",
            return_value=mock_service,
        ):
            # Should not raise
            await notify_tool_call(
                tool=mock_tool,
                args={},
                tool_context=as_tool_context(mock_context),
            )

    @pytest.mark.asyncio
    async def test_notify_tool_call_with_empty_args(self) -> None:
        """Test notification with empty args dict (converted to None)."""
        mock_tool = make_mock_tool(name="list_reminders")
        mock_state = MockState({"user_id": "123456"})
        mock_context = MockToolContext(state=mock_state)

        mock_service = MagicMock()
        mock_service.notify_tool_call = AsyncMock()

        with patch(
            "agent.telegram.notifications.get_notification_service",
            return_value=mock_service,
        ):
            await notify_tool_call(
                tool=mock_tool,
                args={},
                tool_context=as_tool_context(mock_context),
            )

        # Empty dict is falsy, so it gets converted to None
        mock_service.notify_tool_call.assert_called_once_with(
            chat_id="123456",
            tool_name="list_reminders",
            args=None,
        )

    @pytest.mark.asyncio
    async def test_notify_tool_call_with_non_empty_args(self) -> None:
        """Test notification with args."""
        mock_tool = make_mock_tool(name="get_stats")
        mock_state = MockState({"user_id": "123456"})
        mock_context = MockToolContext(state=mock_state)

        mock_service = MagicMock()
        mock_service.notify_tool_call = AsyncMock()

        with patch(
            "agent.telegram.notifications.get_notification_service",
            return_value=mock_service,
        ):
            await notify_tool_call(
                tool=mock_tool,
                args={"count": 10},
                tool_context=as_tool_context(mock_context),
            )

        mock_service.notify_tool_call.assert_called_once_with(
            chat_id="123456",
            tool_name="get_stats",
            args={"count": 10},
        )
