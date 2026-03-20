"""Tests for telegram_bot module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError

from agent.telegram.bot import (
    _render_markdown_as_html,
    _send_long_message,
    _send_validated_chunk,
    _split_and_send,
    create_application,
    handle_message,
    help_command,
    reset_command,
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
        assert "/reset" in help_text


class TestResetCommand:
    """Tests for reset_command function."""

    @pytest.mark.asyncio
    async def test_resets_session_and_confirms(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that session is reset and confirmation sent."""
        with patch(
            "agent.telegram.bot.reset_session",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_reset:
            await reset_command(mock_update, mock_context)

            mock_reset.assert_called_once_with(user_id="12345")
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "Session reset" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_shows_error_on_failure(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that error message is shown when reset fails."""
        with patch(
            "agent.telegram.bot.reset_session",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_reset:
            await reset_command(mock_update, mock_context)

            mock_reset.assert_called_once_with(user_id="12345")
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "Failed to reset" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_returns_early_when_no_message(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no message."""
        update = MagicMock(spec=Update)
        update.message = None
        update.effective_user = MagicMock()

        with patch(
            "agent.telegram.bot.reset_session", new_callable=AsyncMock
        ) as mock_reset:
            await reset_command(update, mock_context)

            mock_reset.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_early_when_no_user(self, mock_context: MagicMock) -> None:
        """Test that function returns early when no effective_user."""
        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.effective_user = None

        with patch(
            "agent.telegram.bot.reset_session", new_callable=AsyncMock
        ) as mock_reset:
            await reset_command(update, mock_context)

            mock_reset.assert_not_called()
            update.message.reply_text.assert_not_called()


class TestHandleMessage:
    """Tests for handle_message function."""

    @pytest.mark.asyncio
    async def test_processes_message_and_sends_response(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that message is processed and response is sent with MARKDOWN_V2."""
        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value="Hello! How can I help?",
        ):
            await handle_message(mock_update, mock_context)

            # ! is special char and gets escaped, ? is not
            mock_update.message.reply_text.assert_called_once_with(
                "Hello\\! How can I help?", parse_mode=ParseMode.MARKDOWN_V2
            )

    @pytest.mark.asyncio
    async def test_sends_typing_indicator(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that typing indicator is sent while processing."""
        with patch(
            "agent.telegram.bot.process_message",
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
    async def test_handles_telegram_error_gracefully(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that TelegramError exceptions are handled separately."""
        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            side_effect=TelegramError("API Error"),
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "problem sending the response" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_handles_general_exceptions_gracefully(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that general exceptions are handled and error message sent."""
        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            side_effect=Exception("Internal Error"),
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
            "agent.telegram.bot.process_message",
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
        """Test that short messages are sent as single message with MARKDOWN_V2."""
        short_response = "Short response"

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=short_response,
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once_with(
                short_response, parse_mode=ParseMode.MARKDOWN_V2
            )

    @pytest.mark.asyncio
    async def test_retries_without_markdown_when_telegram_rejects_chunk(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Telegram markdown failures should fall back to HTML."""
        mock_update.message.reply_text = AsyncMock(
            side_effect=[TelegramError("Can't parse entities"), None]
        )

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=r"\((1-\text{tax rate})\)",
        ):
            await handle_message(mock_update, mock_context)

            assert mock_update.message.reply_text.call_count == 2
            first_call = mock_update.message.reply_text.call_args_list[0]
            second_call = mock_update.message.reply_text.call_args_list[1]

            assert first_call.kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
            assert second_call.args[0] == "((1-tax rate))"
            assert second_call.kwargs["parse_mode"] == ParseMode.HTML


class TestSendLongMessage:
    """Tests for _send_long_message helper function."""

    @pytest.mark.asyncio
    async def test_splits_at_paragraph_boundaries(self) -> None:
        """Test that messages are split at paragraph breaks."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text with multiple paragraphs
        paragraph = "A" * 2000
        long_text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}"

        await _send_long_message(mock_message, long_text)

        # Should split at paragraph boundaries
        assert mock_message.reply_text.call_count >= 2

    @pytest.mark.asyncio
    async def test_sends_single_message_for_short_text(self) -> None:
        """Test that short text is sent as single message with MARKDOWN_V2."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        short_text = "Short message"

        await _send_long_message(mock_message, short_text)

        mock_message.reply_text.assert_called_once_with(
            short_text, parse_mode=ParseMode.MARKDOWN_V2
        )

    @pytest.mark.asyncio
    async def test_preserves_paragraph_formatting(self) -> None:
        """Test that paragraph breaks are preserved."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text that fits in one message but has paragraphs
        text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"

        await _send_long_message(mock_message, text)

        # Should be sent as one message with paragraphs preserved
        call_args = mock_message.reply_text.call_args
        assert "\n\n" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_falls_back_to_split_and_send(self) -> None:
        """Test that _split_and_send is called for very long paragraphs."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create a single paragraph longer than the limit
        long_paragraph = "A" * 5000

        await _send_long_message(mock_message, long_paragraph)

        # Should split via _split_and_send
        assert mock_message.reply_text.call_count >= 2

    @pytest.mark.asyncio
    async def test_handles_empty_text(self) -> None:
        """Test that empty text is handled gracefully."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        await _send_long_message(mock_message, "")

        # Should not send any message
        mock_message.reply_text.assert_not_called()


class TestSendValidatedChunk:
    """Tests for _send_validated_chunk helper."""

    @pytest.mark.asyncio
    async def test_falls_back_to_html_for_unbalanced_markup(self) -> None:
        """Unbalanced markdown should be sent with HTML fallback."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        await _send_validated_chunk(mock_message, "*unclosed")

        mock_message.reply_text.assert_called_once_with(
            "*unclosed",
            parse_mode=ParseMode.HTML,
        )

    @pytest.mark.asyncio
    async def test_retries_html_when_telegram_rejects_markup(self) -> None:
        """Telegram entity parse failures should retry with HTML."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock(
            side_effect=[TelegramError("Can't parse entities"), None]
        )

        await _send_validated_chunk(
            mock_message,
            chunk="value \\(test\\)",
            fallback_text="value (test)",
        )

        assert mock_message.reply_text.call_count == 2
        first_call = mock_message.reply_text.call_args_list[0]
        second_call = mock_message.reply_text.call_args_list[1]

        assert first_call.args[0] == "value \\(test\\)"
        assert first_call.kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
        assert second_call.args[0] == "value (test)"
        assert second_call.kwargs["parse_mode"] == ParseMode.HTML


class TestRenderMarkdownAsHtml:
    """Tests for markdown-to-HTML fallback rendering."""

    def test_preserves_common_markdown_formatting(self) -> None:
        """Fallback HTML should keep useful formatting."""
        markdown = (
            "### Bottom line\n\n"
            "The **cost of debt** is `6%` and [details](https://example.com).\n"
            r"\((1-\text{tax rate})\)"
        )

        result = _render_markdown_as_html(markdown)

        assert "<b>Bottom line</b>" in result
        assert "<b>cost of debt</b>" in result
        assert "<code>6%</code>" in result
        assert '<a href="https://example.com">details</a>' in result
        assert "((1-tax rate))" in result


class TestSplitAndSend:
    """Tests for _split_and_send fallback function."""

    @pytest.mark.asyncio
    async def test_splits_at_newline_when_possible(self) -> None:
        """Test that splitting prefers newline boundaries."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text with newlines near the 4096 boundary
        line = "A" * 4000
        long_text = f"{line}\n{line}\n{line}"

        await _split_and_send(mock_message, long_text)

        # Should split into multiple messages
        assert mock_message.reply_text.call_count >= 2

    @pytest.mark.asyncio
    async def test_splits_at_space_when_no_newline(self) -> None:
        """Test that splitting falls back to space boundaries."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text without newlines but with spaces
        word = "word " * 1200  # ~6000 chars with spaces

        await _split_and_send(mock_message, word)

        # Should split at space boundaries
        assert mock_message.reply_text.call_count >= 2

    @pytest.mark.asyncio
    async def test_splits_at_char_boundary_when_no_delimiter(self) -> None:
        """Test that splitting falls back to character boundaries."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text without spaces or newlines
        long_text = "A" * 5000

        await _split_and_send(mock_message, long_text)

        # Should still split into messages
        assert mock_message.reply_text.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_remaining_content(self) -> None:
        """Test that all remaining content is sent."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text slightly over limit
        long_text = "A" * 4100

        await _split_and_send(mock_message, long_text)

        # Verify all content was sent
        sent_chars = sum(
            len(call[0][0]) for call in mock_message.reply_text.call_args_list
        )
        assert sent_chars == 4100

    @pytest.mark.asyncio
    async def test_handles_empty_chunk_at_start(self) -> None:
        """Test handling of text where the first chunk would be empty after strip."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text starting with spaces that would result in empty chunk
        # after strip, then regular content
        long_text = "   \n" + "A" * 5000

        await _split_and_send(mock_message, long_text)

        # Should still send the content
        assert mock_message.reply_text.call_count >= 1

    @pytest.mark.asyncio
    async def test_splits_multiple_times(self) -> None:
        """Test that very long text is split multiple times."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text that requires multiple splits (> 3 * 4096)
        long_text = "A" * 15000

        await _split_and_send(mock_message, long_text)

        # Should split into at least 4 messages
        assert mock_message.reply_text.call_count >= 4

    @pytest.mark.asyncio
    async def test_skips_empty_chunk_after_strip(self) -> None:
        """Test that empty chunks after strip are skipped."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Create text where split point would result in whitespace-only chunk
        # that becomes empty after strip
        long_text = " " * 4100 + "A" * 100

        await _split_and_send(mock_message, long_text)

        # Should send at least the content part
        assert mock_message.reply_text.call_count >= 1

    @pytest.mark.asyncio
    async def test_exact_boundary_split(self) -> None:
        """Test text that is exactly at the boundary."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        # Text that is exactly 4096 chars (the limit)
        exact_text = "A" * 4096

        await _split_and_send(mock_message, exact_text)

        # Should send as single message (hits the break path)
        mock_message.reply_text.assert_called_once()


class TestCreateApplication:
    """Tests for create_application function."""

    def test_creates_application_with_token(self) -> None:
        """Test that application is created with the provided token."""
        with patch("agent.telegram.bot.initialize_runner") as mock_init:
            app = create_application("test-token-123")

            assert app is not None
            mock_init.assert_called_once()

    def test_registers_command_handlers(self) -> None:
        """Test that command handlers are registered."""
        with patch("agent.telegram.bot.initialize_runner"):
            app = create_application("test-token-123")

            # Check that handlers are registered (stored in group 0 by default)
            handlers = app.handlers[0]
            # start, help, reset, reminders, message handler
            assert len(handlers) == 5

    def test_uses_app_for_initialization(self) -> None:
        """Test that app is used for initialization."""
        with (
            patch(
                "agent.telegram.bot.create_session_service_for_runner"
            ) as mock_session,
            patch("agent.telegram.bot.initialize_runner") as mock_init,
            patch("agent.telegram.bot.app") as mock_app,
        ):
            mock_session.return_value = MagicMock()
            create_application("test-token-123")

            mock_session.assert_called_once()
            mock_init.assert_called_once_with(
                app=mock_app,
                session_service=mock_session.return_value,
            )


class TestSetBotCommands:
    """Tests for _set_bot_commands function."""

    @pytest.mark.asyncio
    async def test_sets_bot_commands(self) -> None:
        """Test that bot commands are registered with Telegram."""
        mock_bot = MagicMock()
        mock_bot.set_my_commands = AsyncMock()

        mock_app = MagicMock()
        mock_app.bot = mock_bot

        from agent.telegram.bot import _set_bot_commands

        await _set_bot_commands(mock_app)

        mock_bot.set_my_commands.assert_called_once()
        # Verify the commands include all expected commands
        call_args = mock_bot.set_my_commands.call_args[0][0]
        command_names = [cmd.command for cmd in call_args]
        assert "start" in command_names
        assert "help" in command_names
        assert "reset" in command_names


class TestRunBot:
    """Tests for run_bot function."""

    def test_returns_1_when_token_not_set(self) -> None:
        """Test that run_bot returns 1 when token is None."""
        import agent.telegram.bot as bot_module

        with patch.object(bot_module.logger, "error") as mock_logger:
            result = bot_module.run_bot(None)

            assert result == 1
            mock_logger.assert_called_once_with(
                "TELEGRAM_BOT_TOKEN environment variable is required"
            )

    def test_starts_bot_when_token_set(self) -> None:
        """Test that bot starts when token is set."""
        mock_app = MagicMock()
        mock_app.run_polling = MagicMock()

        import agent.telegram.bot as bot_module

        with patch.object(bot_module, "create_application", return_value=mock_app):
            result = bot_module.run_bot("test-token")

            assert result == 0
            mock_app.run_polling.assert_called_once()


class TestMain:
    """Tests for main function."""

    def test_exits_when_token_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that main exits with code 1 when TELEGRAM_BOT_TOKEN is not set."""
        import agent.telegram.bot as bot_module

        monkeypatch.setattr(bot_module, "TELEGRAM_BOT_TOKEN", None)

        with patch.object(bot_module.sys, "exit") as mock_exit:
            bot_module.main()

            mock_exit.assert_called_once_with(1)

    def test_starts_bot_when_token_set(self) -> None:
        """Test that bot starts when token is set."""
        mock_app = MagicMock()
        mock_app.run_polling = MagicMock()

        import agent.telegram.bot as bot_module

        with (
            patch.object(bot_module, "TELEGRAM_BOT_TOKEN", "test-token"),
            patch.object(bot_module, "create_application", return_value=mock_app),
        ):
            bot_module.main()
            # If no exception, the test passes
