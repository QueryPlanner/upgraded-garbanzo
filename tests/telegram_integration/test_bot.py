"""Tests for telegram_bot module."""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError

from agent.telegram.bot import (
    TELEGRAM_DOCUMENT_CAPTION_MAX,
    TELEGRAM_MAX_CONCURRENT_UPDATES,
    _render_markdown_as_html,
    _send_long_message,
    _send_queued_telegram_documents,
    _send_validated_chunk,
    _split_and_send,
    _telegram_html_tag_stack_valid,
    create_application,
    handle_message,
    help_command,
    model_command,
    reset_command,
    start_command,
    tokens_command,
)
from agent.telegram.handler import TelegramAgentReply
from agent.telegram_prefs import (
    TELEGRAM_SESSION_LITELLM_MODEL_KEY,
    TELEGRAM_SESSION_PROVIDER_KEY,
    TELEGRAM_USAGE_PROMPT_KEY,
)
from agent.utils.telegram_outbox import PendingTelegramFile


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
    context.bot.send_document = AsyncMock()
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
        """Test that message is processed and response is sent with HTML."""
        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text="Hello! How can I help?"),
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once_with(
                "Hello! How can I help?",
                parse_mode=ParseMode.HTML,
            )

    @pytest.mark.asyncio
    async def test_sends_typing_indicator(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that typing indicator is sent while processing."""
        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text="Response"),
        ):
            await handle_message(mock_update, mock_context)
            # Typing runs in a background task; yield so it can complete.
            await asyncio.sleep(0)

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
    async def test_skips_superseded_reply(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """A superseded turn should not send stale text or fallback output."""
        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text="", superseded=True),
        ):
            await handle_message(mock_update, mock_context)

        mock_update.message.reply_text.assert_not_called()

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
            return_value=TelegramAgentReply(text=long_response),
        ):
            await handle_message(mock_update, mock_context)

            # Should be called twice (4096 + 904)
            assert mock_update.message.reply_text.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_single_message_when_under_limit(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Test that short messages are sent as single HTML message."""
        short_response = "Short response"

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text=short_response),
        ):
            await handle_message(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once_with(
                short_response, parse_mode=ParseMode.HTML
            )

    @pytest.mark.asyncio
    async def test_forwards_streamed_text_chunks_without_duplicate_final_send(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Visible mid-turn text should be delivered immediately and not resent."""

        async def mock_process_message(**kwargs: object) -> TelegramAgentReply:
            on_text_chunk = kwargs["on_text_chunk"]
            assert callable(on_text_chunk)
            await on_text_chunk("First streamed chunk.")
            await on_text_chunk("Second streamed chunk.")
            return TelegramAgentReply(
                text="First streamed chunk.Second streamed chunk.",
                streamed_text=True,
            )

        with patch(
            "agent.telegram.bot.process_message",
            side_effect=mock_process_message,
        ):
            await handle_message(mock_update, mock_context)

        assert mock_update.message.reply_text.call_count == 2
        first_call = mock_update.message.reply_text.call_args_list[0]
        second_call = mock_update.message.reply_text.call_args_list[1]
        assert first_call.args[0] == "First streamed chunk."
        assert second_call.args[0] == "Second streamed chunk."
        assert first_call.kwargs["parse_mode"] == ParseMode.HTML
        assert second_call.kwargs["parse_mode"] == ParseMode.HTML

    @pytest.mark.asyncio
    async def test_retries_without_markdown_when_telegram_rejects_chunk(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """Telegram HTML failures should fall back to plain text."""
        mock_update.message.reply_text = AsyncMock(
            side_effect=[TelegramError("Can't parse entities"), None]
        )

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text=r"\((1-\text{tax rate})\)"),
        ):
            await handle_message(mock_update, mock_context)

            assert mock_update.message.reply_text.call_count == 2
            first_call = mock_update.message.reply_text.call_args_list[0]
            second_call = mock_update.message.reply_text.call_args_list[1]

            assert first_call.kwargs["parse_mode"] == ParseMode.HTML
            assert second_call.args[0] == r"\((1-\text{tax rate})\)"
            assert "parse_mode" not in second_call.kwargs

    @pytest.mark.asyncio
    async def test_passes_latex_style_text_through_without_dropping_reply(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        """LaTeX-style text should still be delivered as plain visible text."""
        response = (
            r"\["
            r"\text{After-tax cost of debt} = "
            r"\underbrace{r_{\text{pre}}}{\text{interest rate}} "
            r"\times \Bigl(1 - T\Bigr)"
            r"\]"
        )

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text=response),
        ):
            await handle_message(mock_update, mock_context)

            sent_text = mock_update.message.reply_text.call_args.args[0]

            assert r"\text{After-tax cost of debt}" in sent_text
            assert "interest rate" in sent_text
            assert mock_update.message.reply_text.call_args.kwargs["parse_mode"] == (
                ParseMode.HTML
            )

    @pytest.mark.asyncio
    async def test_sends_queued_documents_after_reply(
        self, mock_update: MagicMock, mock_context: MagicMock, tmp_path: Path
    ) -> None:
        """Files queued by tools are sent via send_document after the text reply."""
        doc_path = tmp_path / "attachment.txt"
        doc_path.write_text("payload", encoding="utf-8")
        doc = PendingTelegramFile(
            path=doc_path,
            caption="file caption",
            filename="attachment.txt",
        )

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value=TelegramAgentReply(text="Here is the file.", documents=(doc,)),
        ):
            await handle_message(mock_update, mock_context)

        mock_context.bot.send_document.assert_called_once()
        kwargs = mock_context.bot.send_document.call_args.kwargs
        assert kwargs["chat_id"] == 67890
        assert kwargs["caption"] == "file caption"
        assert kwargs["document"].filename == "attachment.txt"
        assert not doc_path.exists()

    @pytest.mark.asyncio
    async def test_send_queued_truncates_long_caption(self, tmp_path: Path) -> None:
        bot = MagicMock()
        bot.send_document = AsyncMock()
        long_caption = "x" * (TELEGRAM_DOCUMENT_CAPTION_MAX + 500)
        doc_path = tmp_path / "f.txt"
        doc_path.write_text("a", encoding="utf-8")
        doc = PendingTelegramFile(path=doc_path, caption=long_caption, filename="f.txt")
        await _send_queued_telegram_documents(bot, 1, (doc,))
        sent = bot.send_document.call_args.kwargs["caption"]
        assert len(sent) == TELEGRAM_DOCUMENT_CAPTION_MAX
        assert sent.endswith("…")
        assert not doc_path.exists()

    @pytest.mark.asyncio
    async def test_send_queued_logs_on_telegram_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bot = MagicMock()
        bot.send_document = AsyncMock(side_effect=TelegramError("network"))
        doc_path = tmp_path / "f.txt"
        doc_path.write_text("a", encoding="utf-8")
        doc = PendingTelegramFile(path=doc_path, caption=None, filename="x.txt")
        with caplog.at_level(logging.WARNING, logger="agent.telegram.bot"):
            await _send_queued_telegram_documents(bot, 99, (doc,))
        assert any(
            "Failed to send Telegram document" in r.message for r in caplog.records
        )
        assert not doc_path.exists()


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
        """Test that short text is sent as single message with HTML."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        short_text = "Short message"

        await _send_long_message(mock_message, short_text)

        mock_message.reply_text.assert_called_once_with(
            short_text, parse_mode=ParseMode.HTML
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
        """Chunks are sent with HTML parse mode by default."""
        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        await _send_validated_chunk(mock_message, "*unclosed")

        mock_message.reply_text.assert_called_once_with(
            "*unclosed",
            parse_mode=ParseMode.HTML,
        )

    @pytest.mark.asyncio
    async def test_retries_plain_text_when_telegram_rejects_html(self) -> None:
        """Telegram HTML failures should retry without formatting."""
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
        assert first_call.kwargs["parse_mode"] == ParseMode.HTML
        assert second_call.args[0] == "value (test)"
        assert "parse_mode" not in second_call.kwargs


class TestRenderMarkdownAsHtml:
    """Tests for markdown-to-HTML fallback rendering."""

    def test_empty_markdown_returns_empty(self) -> None:
        assert _render_markdown_as_html("") == ""

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
        assert r"\((1-\text{tax rate})\)" in result

    def test_inline_code_before_italic_avoids_crossed_tags(self) -> None:
        """Underscores inside backticks must not become <i> wrappers."""
        markdown = "Use `snake_case` for *italic* only."
        result = _render_markdown_as_html(markdown)
        assert "<code>snake_case</code>" in result
        assert "<i>italic</i>" in result
        assert "</i></code>" not in result
        assert "</code></i>" not in result

    def test_fenced_code_preserves_asterisks_without_bold(self) -> None:
        markdown = "```\n**not bold**\n```"
        result = _render_markdown_as_html(markdown)
        assert "<pre>" in result
        assert "**not bold**" in result
        assert "<b>not bold</b>" not in result

    def test_telegram_html_stack_rejects_unclosed_tags(self) -> None:
        """Validator must catch unclosed formatting so callers can fall back."""
        assert _telegram_html_tag_stack_valid("<b>only open") is False
        assert _telegram_html_tag_stack_valid("<b>ok</b>") is True

    def test_telegram_html_stack_anchor_mismatch(self) -> None:
        """Mis-nested or orphan anchor tags must fail validation."""
        assert _telegram_html_tag_stack_valid('<a href="https://x">x</a>') is True
        assert _telegram_html_tag_stack_valid("</a>") is False
        assert _telegram_html_tag_stack_valid('<a href="https://x">x') is False

    def test_telegram_html_stack_rejects_mismatched_close_tag(self) -> None:
        assert _telegram_html_tag_stack_valid("<i>x</b>") is False

    def test_split_handles_unclosed_fence_and_backtick(self) -> None:
        """Unclosed constructs are treated as literal text where appropriate."""
        from agent.telegram.bot import _split_markdown_to_segments

        segs = _split_markdown_to_segments("```\nno closing")
        assert [s[0] for s in segs] == ["text"]
        assert segs[0][1] == "```\nno closing"

        segs2 = _split_markdown_to_segments("no ` closing")
        assert all(s[0] == "text" for s in segs2)
        assert "".join(s[1] for s in segs2) == "no ` closing"

    def test_render_falls_back_to_escaped_plain_when_stack_invalid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If post-render HTML is invalid, send fully escaped source markdown."""
        monkeypatch.setattr(
            "agent.telegram.bot._telegram_html_tag_stack_valid",
            lambda _fragment: False,
        )
        assert _render_markdown_as_html("hello **world**") == "hello **world**"

    def test_render_unknown_segment_kind_is_escaped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unexpected segment tuples are stringified and escaped."""

        def fake_segments(_t: str) -> list[tuple[str, ...]]:
            return [("bogus", "x")]

        monkeypatch.setattr(
            "agent.telegram.bot._split_markdown_to_segments",
            fake_segments,
        )
        out = _render_markdown_as_html("ignored")
        assert "bogus" in out


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
            # start, help, reset, model, tokens, reminders, message
            assert len(handlers) == 7

    def test_enables_concurrent_update_processing(self) -> None:
        """Telegram steering needs updates to be processed concurrently."""
        with patch("agent.telegram.bot.initialize_runner"):
            app = create_application("test-token-123")

        assert (
            app.update_processor.max_concurrent_updates
            == TELEGRAM_MAX_CONCURRENT_UPDATES
        )

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


class TestInitializeObservability:
    """Tests for Telegram observability bootstrap."""

    def test_initializes_observability_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bootstrap OTel and logging once even if called repeatedly."""
        import agent.telegram.bot as bot_module

        monkeypatch.setattr(bot_module, "_TELEGRAM_OBSERVABILITY_INITIALIZED", False)
        monkeypatch.setenv("AGENT_NAME", "telegram-agent")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        mock_instrumentor = MagicMock()

        with (
            patch.object(bot_module, "configure_otel_resource") as mock_configure,
            patch.object(bot_module, "setup_logging") as mock_setup_logging,
            patch.object(
                bot_module,
                "GoogleADKInstrumentor",
                return_value=mock_instrumentor,
            ) as mock_instrumentor_class,
        ):
            bot_module._initialize_observability()
            bot_module._initialize_observability()

        mock_configure.assert_called_once_with(agent_name="telegram-agent")
        mock_instrumentor_class.assert_called_once_with()
        mock_instrumentor.instrument.assert_called_once_with()
        mock_setup_logging.assert_called_once_with(log_level="DEBUG")

    def test_falls_back_to_app_name_when_agent_name_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Use the ADK app name when AGENT_NAME is not configured."""
        import agent.telegram.bot as bot_module

        monkeypatch.setattr(bot_module, "_TELEGRAM_OBSERVABILITY_INITIALIZED", False)
        monkeypatch.delenv("AGENT_NAME", raising=False)
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        mock_instrumentor = MagicMock()

        with (
            patch.object(bot_module, "configure_otel_resource") as mock_configure,
            patch.object(bot_module, "setup_logging"),
            patch.object(
                bot_module,
                "GoogleADKInstrumentor",
                return_value=mock_instrumentor,
            ),
        ):
            bot_module._initialize_observability()

        mock_configure.assert_called_once_with(agent_name=bot_module.app.name)


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
        assert "model" in command_names
        assert "tokens" in command_names
        assert "reminders" in command_names


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

        with (
            patch.object(bot_module, "_initialize_observability") as mock_init_obs,
            patch.object(bot_module, "create_application", return_value=mock_app),
        ):
            result = bot_module.run_bot("test-token")

            assert result == 0
            mock_init_obs.assert_called_once_with()
            mock_app.run_polling.assert_called_once()


class TestSlashModelCommands:
    """Tests for /model and /tokens slash commands."""

    @staticmethod
    def _handler_with_sessions() -> MagicMock:
        from google.adk.sessions.in_memory_session_service import (
            InMemorySessionService,
        )

        svc = InMemorySessionService()
        mock_h = MagicMock()
        mock_h.app_name = "agent"
        mock_h.runner = MagicMock()
        mock_h.runner.session_service = svc
        return mock_h

    @pytest.mark.asyncio
    async def test_model_command_lists_models(
        self, mock_update: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_h = self._handler_with_sessions()
        await mock_h.runner.session_service.create_session(
            app_name="agent",
            user_id="12345",
            session_id="12345",
            state={
                "user_id": "12345",
                TELEGRAM_SESSION_PROVIDER_KEY: "openrouter",
            },
        )
        ctx = MagicMock()
        ctx.args = []
        monkeypatch.delenv("ROOT_AGENT_MODEL", raising=False)

        with patch("agent.telegram.bot.get_handler", return_value=mock_h):
            await model_command(mock_update, ctx)

        mock_update.message.reply_text.assert_called_once()
        call = mock_update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        assert "1." in text
        assert "openrouter" in text
        assert "z-ai/glm-4.7" in text

    @pytest.mark.asyncio
    async def test_model_command_sets_model(self, mock_update: MagicMock) -> None:
        mock_h = self._handler_with_sessions()
        await mock_h.runner.session_service.create_session(
            app_name="agent",
            user_id="12345",
            session_id="12345",
            state={
                "user_id": "12345",
                TELEGRAM_SESSION_PROVIDER_KEY: "openai",
            },
        )
        ctx = MagicMock()
        ctx.args = ["2"]

        with patch("agent.telegram.bot.get_handler", return_value=mock_h):
            await model_command(mock_update, ctx)

        session = await mock_h.runner.session_service.get_session(
            app_name="agent",
            user_id="12345",
            session_id="12345",
        )
        assert session is not None
        assert session.state.get(TELEGRAM_SESSION_LITELLM_MODEL_KEY) == "openai/glm-5"

    @pytest.mark.asyncio
    async def test_tokens_command_shows_usage(self, mock_update: MagicMock) -> None:
        mock_h = self._handler_with_sessions()
        await mock_h.runner.session_service.create_session(
            app_name="agent",
            user_id="12345",
            session_id="12345",
            state={
                "user_id": "12345",
                TELEGRAM_USAGE_PROMPT_KEY: 42,
            },
        )
        ctx = MagicMock()

        with patch("agent.telegram.bot.get_handler", return_value=mock_h):
            await tokens_command(mock_update, ctx)

        call = mock_update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        assert "42" in text


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
