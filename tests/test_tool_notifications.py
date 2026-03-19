"""Tests for the tool notification service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.telegram.notifications import (
    ToolNotificationService,
    get_notification_service,
)


class TestToolNotificationService:
    """Tests for ToolNotificationService class."""

    def test_init_default_values(self) -> None:
        """Test default initialization."""
        service = ToolNotificationService()
        assert service._bot is None
        assert service._enabled is True

    def test_init_with_bot_and_enabled(self) -> None:
        """Test initialization with bot and enabled flag."""
        mock_bot = MagicMock()
        service = ToolNotificationService(bot=mock_bot, enabled=False)
        assert service._bot is mock_bot
        assert service._enabled is False

    def test_set_bot(self) -> None:
        """Test setting bot instance."""
        service = ToolNotificationService()
        mock_bot = MagicMock()
        service.set_bot(mock_bot)
        assert service._bot is mock_bot

    def test_bot_property_raises_when_not_set(self) -> None:
        """Test bot property raises RuntimeError when not set."""
        service = ToolNotificationService()
        with pytest.raises(RuntimeError, match="Bot not set"):
            _ = service.bot

    def test_bot_property_returns_bot(self) -> None:
        """Test bot property returns the bot instance."""
        mock_bot = MagicMock()
        service = ToolNotificationService(bot=mock_bot)
        assert service.bot is mock_bot

    def test_enabled_property(self) -> None:
        """Test enabled property."""
        service = ToolNotificationService(enabled=True)
        assert service.enabled is True

        service.set_enabled(False)
        assert service.enabled is False

    @pytest.mark.asyncio
    async def test_notify_tool_call_disabled(self) -> None:
        """Test notification is skipped when disabled."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        service = ToolNotificationService(bot=mock_bot, enabled=False)

        await service.notify_tool_call(
            chat_id="123",
            tool_name="test_tool",
            args={"key": "value"},
        )

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_tool_call_no_bot(self) -> None:
        """Test notification is skipped when bot is not set."""
        service = ToolNotificationService(enabled=True)

        # Should not raise, just return
        await service.notify_tool_call(
            chat_id="123",
            tool_name="test_tool",
            args={"key": "value"},
        )

    @pytest.mark.asyncio
    async def test_notify_tool_call_success(self) -> None:
        """Test successful tool call notification."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        service = ToolNotificationService(bot=mock_bot, enabled=True)

        await service.notify_tool_call(
            chat_id="123",
            tool_name="test_tool",
            args={"key": "value"},
        )

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs["chat_id"] == "123"
        assert "test_tool" in call_args.kwargs["text"]
        assert "key" in call_args.kwargs["text"]
        assert call_args.kwargs["parse_mode"] == "Markdown"

    @pytest.mark.asyncio
    async def test_notify_tool_call_no_args(self) -> None:
        """Test notification without args."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        service = ToolNotificationService(bot=mock_bot, enabled=True)

        await service.notify_tool_call(
            chat_id="123",
            tool_name="test_tool",
        )

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert "test_tool" in call_args.kwargs["text"]
        assert "Args" not in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_notify_tool_call_truncates_long_args(self) -> None:
        """Test that long args are truncated."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        service = ToolNotificationService(bot=mock_bot, enabled=True)

        # Create args longer than 200 chars
        long_args = {"data": "x" * 300}

        await service.notify_tool_call(
            chat_id="123",
            tool_name="test_tool",
            args=long_args,
        )

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        # Should contain truncated args (ending with ...)
        text = call_args.kwargs["text"]
        assert "..." in text

    @pytest.mark.asyncio
    async def test_notify_tool_call_handles_exception(self) -> None:
        """Test that exceptions during send are handled gracefully."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=Exception("Send failed"))
        service = ToolNotificationService(bot=mock_bot, enabled=True)

        # Should not raise
        await service.notify_tool_call(
            chat_id="123",
            tool_name="test_tool",
        )


class TestGetNotificationService:
    """Tests for get_notification_service singleton."""

    def test_returns_singleton(self) -> None:
        """Test that get_notification_service returns the same instance."""
        with patch("agent.telegram.notifications._notification_service", None):
            service1 = get_notification_service()
            service2 = get_notification_service()
            assert service1 is service2

    def test_creates_new_instance_when_none(self) -> None:
        """Test that a new instance is created when none exists."""
        with patch("agent.telegram.notifications._notification_service", None):
            service = get_notification_service()
            assert isinstance(service, ToolNotificationService)
            assert service._bot is None
            assert service._enabled is True
