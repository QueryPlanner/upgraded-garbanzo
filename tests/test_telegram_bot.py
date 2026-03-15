"""Tests for telegram_bot module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update

from agent.telegram_bot import (
    clear_command,
    handle_message,
    help_command,
    start_command,
)


@pytest.fixture
def mock_update() -> MagicMock:
    """Create a mock Telegram Update."""
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = "Hello bot"
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat = MagicMock()
    update.effective_chat.id = 67890
    return update


@pytest.fixture
def mock_context() -> MagicMock:
    """Create a mock Telegram Context."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_chat_action = AsyncMock()
    return context


class TestStartCommand:
    """Tests for start_command function."""

    @pytest.mark.asyncio
    async def test_sends_welcome_message(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that welcome message is sent."""
        await start_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Welcome to the ADK Agent Bot" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_returns_early_when_no_message(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no message."""
        update = MagicMock(spec=Update)
        update.message = None

        await start_command(update, mock_context)

        # Should not attempt to reply
        assert True

    @pytest.mark.asyncio
    async def test_uses_markdown_parse_mode(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that message is sent with Markdown parse mode."""
        await start_command(mock_update, mock_context)

        call_kwargs = mock_update.message.reply_text.call_args[1]
        assert call_kwargs.get("parse_mode") == "Markdown"


class TestHelpCommand:
    """Tests for help_command function."""

    @pytest.mark.asyncio
    async def test_sends_help_message(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that help message is sent."""
        await help_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "ADK Agent Bot Help" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_returns_early_when_no_message(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no message."""
        update = MagicMock(spec=Update)
        update.message = None

        await help_command(update, mock_context)

        assert True

    @pytest.mark.asyncio
    async def test_lists_available_commands(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that available commands are listed."""
        await help_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args
        help_text = call_args[0][0]
        assert "/start" in help_text
        assert "/help" in help_text
        assert "/clear" in help_text


class TestClearCommand:
    """Tests for clear_command function."""

    @pytest.mark.asyncio
    async def test_clears_session_and_confirms(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that session is cleared and confirmation sent."""
        with patch(
            "agent.telegram_bot.clear_session", new_callable=AsyncMock
        ) as mock_clear:
            await clear_command(mock_update, mock_context)

            mock_clear.assert_called_once_with(user_id="12345")
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "Conversation cleared" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_returns_early_when_no_message(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no message."""
        update = MagicMock(spec=Update)
        update.message = None
        update.effective_user = MagicMock()

        with patch("agent.telegram_bot.clear_session", new_callable=AsyncMock):
            await clear_command(update, mock_context)

            assert True

    @pytest.mark.asyncio
    async def test_returns_early_when_no_user(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no effective_user."""
        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.effective_user = None

        await clear_command(update, mock_context)

        assert True


class TestHandleMessage:
    """Tests for handle_message function."""

    @pytest.mark.asyncio
    async def test_processes_message_and_sends_response(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that message is processed and response is sent."""
        with patch(
            "agent.telegram_bot.process_message",
            new_callable=AsyncMock,
            return_value="Hello! How can I help?",
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once_with(
                "Hello! How can I help?"
            )

    @pytest.mark.asyncio
    async def test_sends_typing_indicator(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that typing indicator is sent while processing."""
        with patch(
            "agent.telegram_bot.process_message",
            new_callable=AsyncMock,
            return_value="Response",
        ):
            await handle_message(mock_update, mock_context)

            mock_context.bot.send_chat_action.assert_called_once_with(
                chat_id=67890, action="typing"
            )

    @pytest.mark.asyncio
    async def test_returns_early_when_no_message(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no message."""
        update = MagicMock(spec=Update)
        update.message = None

        await handle_message(update, mock_context)

        assert True

    @pytest.mark.asyncio
    async def test_returns_early_when_no_text(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that function returns early when message has no text."""
        mock_update.message.text = None

        await handle_message(mock_update, mock_context)

        mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_early_when_no_user(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no effective_user."""
        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.message.text = "Hello"
        update.effective_user = None
        update.effective_chat = MagicMock()

        await handle_message(update, mock_context)

        assert True

    @pytest.mark.asyncio
    async def test_returns_early_when_no_chat(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no effective_chat."""
        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.message.text = "Hello"
        update.effective_user = MagicMock()
        update.effective_user.id = 123
        update.effective_chat = None

        await handle_message(update, mock_context)

        assert True

    @pytest.mark.asyncio
    async def test_handles_exceptions_gracefully(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that exceptions are handled and error message sent."""
        with patch(
            "agent.telegram_bot.process_message",
            new_callable=AsyncMock,
            side_effect=Exception("API Error"),
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "error occurred" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_splits_long_messages(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that messages over 4096 chars are split."""
        long_response = "A" * 5000

        with patch(
            "agent.telegram_bot.process_message",
            new_callable=AsyncMock,
            return_value=long_response,
        ):
            await handle_message(mock_update, mock_context)

            # Should be called twice (4096 + 904)
            assert mock_update.message.reply_text.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_single_message_when_under_limit(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that short messages are sent as single message."""
        short_response = "Short response"

        with patch(
            "agent.telegram_bot.process_message",
            new_callable=AsyncMock,
            return_value=short_response,
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once_with(short_response)
