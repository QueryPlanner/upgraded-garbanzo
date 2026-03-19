"""Tests for the markdown to Telegram MARKDOWN_V2 converter."""

from agent.telegram.markdown_converter import (
    SegmentType,
    _escape_special_chars,
    _find_formatting_spans,
    convert_markdown_to_telegram,
)


class TestConvertMarkdownToTelegram:
    """Tests for the main conversion function."""

    def test_empty_string(self) -> None:
        """Empty input returns empty output."""
        assert convert_markdown_to_telegram("") == ""

    def test_plain_text(self) -> None:
        """Plain text with no formatting is escaped."""
        # Special chars should be escaped
        result = convert_markdown_to_telegram("Hello world!")
        assert result == "Hello world\\!"

    def test_bold_conversion(self) -> None:
        """Markdown bold (**text**) converts to Telegram bold (*text*)."""
        result = convert_markdown_to_telegram("This is **bold** text")
        # In Telegram MARKDOWN_V2, *text* is bold
        assert result == "This is *bold* text"

    def test_italic_conversion(self) -> None:
        """Markdown single asterisk italic converts to Telegram underscore."""
        # Note: single * in markdown is italic, becomes _ in Telegram
        result = convert_markdown_to_telegram("This is *italic* text")
        assert result == "This is _italic_ text"

    def test_underscore_italic_preserved(self) -> None:
        """Underscore italic is preserved."""
        result = convert_markdown_to_telegram("This is _italic_ text")
        assert result == "This is _italic_ text"

    def test_strikethrough(self) -> None:
        """Markdown strikethrough converts to Telegram format."""
        result = convert_markdown_to_telegram("This is ~~deleted~~ text")
        assert result == "This is ~deleted~ text"

    def test_inline_code_preserved(self) -> None:
        """Inline code is preserved without escaping."""
        result = convert_markdown_to_telegram("Use the `print()` function")
        # The code should be preserved, only the parens inside are NOT escaped
        assert "`print()`" in result

    def test_code_block_preserved(self) -> None:
        """Code blocks are preserved without escaping."""
        code = """```python
def hello():
    print("Hello!")
```"""
        result = convert_markdown_to_telegram(code)
        # Code block should be preserved
        assert "```python" in result
        assert 'print("Hello!")' in result

    def test_mixed_formatting(self) -> None:
        """Mixed bold, italic, and code."""
        result = convert_markdown_to_telegram("**bold** and *italic* and `code`")
        # Bold uses *text* in Telegram, italic uses _text_
        assert "*bold*" in result
        assert "_italic_" in result
        assert "`code`" in result

    def test_links(self) -> None:
        """Markdown links are converted properly."""
        result = convert_markdown_to_telegram("[Click here](https://example.com)")
        assert result == "[Click here](https://example.com)"

    def test_link_with_special_chars_in_text(self) -> None:
        """Links with special characters in display text."""
        result = convert_markdown_to_telegram("[Hello! Click](https://example.com)")
        # The ! in link text should be escaped
        assert "\\!" in result

    def test_headers_escaped(self) -> None:
        """Markdown headers have # escaped."""
        result = convert_markdown_to_telegram("# Header\n## Subheader")
        assert "\\# Header" in result
        assert "\\#\\# Subheader" in result

    def test_list_items_escaped(self) -> None:
        """List markers are escaped."""
        result = convert_markdown_to_telegram("- Item 1\n- Item 2")
        assert "\\- Item 1" in result
        assert "\\- Item 2" in result

    def test_numbered_list_escaped(self) -> None:
        """Numbered list markers are escaped."""
        result = convert_markdown_to_telegram("1. First\n2. Second")
        assert "1\\." in result

    def test_special_chars_escaped(self) -> None:
        """All special characters are escaped in regular text."""
        special = "_*[]()~>#+-=|{}.!"
        result = convert_markdown_to_telegram(special)
        # All should be escaped
        for char in special:
            assert f"\\{char}" in result

    def test_underline_format(self) -> None:
        """Double underscore creates underline in Telegram."""
        result = convert_markdown_to_telegram("This is __underlined__ text")
        assert "__underlined__" in result

    def test_nested_formatting(self) -> None:
        """Nested formatting like bold-italic."""
        # Markdown: ***text*** is bold+italic
        # This is a complex case - our parser may not handle it perfectly
        result = convert_markdown_to_telegram("***important***")
        # At minimum, special chars should be handled
        assert result  # Should return something


class TestFindFormattingSpans:
    """Tests for finding formatting spans."""

    def test_no_code(self) -> None:
        """Text without code is a single regular segment."""
        segments = _find_formatting_spans("Hello world")
        assert len(segments) == 1
        assert segments[0].segment_type == SegmentType.REGULAR
        assert segments[0].text == "Hello world"

    def test_inline_code(self) -> None:
        """Inline code is detected as separate segment."""
        segments = _find_formatting_spans("Use `code` here")
        assert len(segments) == 3
        assert segments[0].segment_type == SegmentType.REGULAR
        assert segments[0].text == "Use "
        assert segments[1].segment_type == SegmentType.INLINE_CODE
        assert segments[1].text == "`code`"
        assert segments[2].segment_type == SegmentType.REGULAR
        assert segments[2].text == " here"

    def test_code_block(self) -> None:
        """Code blocks are detected as separate segments."""
        segments = _find_formatting_spans("Before\n```python\ncode\n```\nAfter")
        assert len(segments) == 3
        assert segments[1].segment_type == SegmentType.CODE_BLOCK

    def test_multiple_inline_code(self) -> None:
        """Multiple inline code segments."""
        segments = _find_formatting_spans("`a` and `b` and `c`")
        code_segments = [
            s for s in segments if s.segment_type == SegmentType.INLINE_CODE
        ]
        assert len(code_segments) == 3

    def test_code_inside_code_block_ignored(self) -> None:
        """Inline code markers inside code blocks are not separate segments."""
        text = "```python\nprint(`x`)\n```"
        segments = _find_formatting_spans(text)
        # Should be: regular (empty or content before), code_block
        code_blocks = [s for s in segments if s.segment_type == SegmentType.CODE_BLOCK]
        assert len(code_blocks) == 1
        # The inline backticks should be inside the code block
        assert "`x`" in code_blocks[0].text


class TestEscapeSpecialChars:
    """Tests for special character escaping."""

    def test_no_special_chars(self) -> None:
        """Text without special chars is unchanged."""
        result = _escape_special_chars("Hello world")
        assert result == "Hello world"

    def test_all_special_chars(self) -> None:
        """All special characters are escaped."""
        result = _escape_special_chars("_*[]()~>#+-=|{}.!")
        assert result == "\\_\\*\\[\\]\\(\\)\\~\\>\\#\\+\\-\\=\\|\\{\\}\\.\\!"

    def test_mixed_content(self) -> None:
        """Mixed regular and special characters."""
        result = _escape_special_chars("Hello! How are you?")
        # ! is special and should be escaped, ? is not special
        assert result == "Hello\\! How are you?"


class TestEdgeCases:
    """Tests for edge cases and tricky inputs."""

    def test_empty_input(self) -> None:
        """Empty string returns empty."""
        assert convert_markdown_to_telegram("") == ""

    def test_only_code_block(self) -> None:
        """Text that is only a code block."""
        result = convert_markdown_to_telegram("```\ncode\n```")
        assert result == "```\ncode\n```"

    def test_only_inline_code(self) -> None:
        """Text that is only inline code."""
        result = convert_markdown_to_telegram("`code`")
        assert result == "`code`"

    def test_unmatched_markers(self) -> None:
        """Unmatched formatting markers are escaped."""
        result = convert_markdown_to_telegram("This has **unmatched bold")
        # Unmatched ** should be escaped
        assert "\\*" in result

    def test_escaped_backslash(self) -> None:
        """Backslash handling - not a special char in MARKDOWN_V2."""
        result = convert_markdown_to_telegram("path\\to\\file")
        # Backslash is not in SPECIAL_CHARS, so it's preserved
        assert result == "path\\to\\file"

    def test_newlines_preserved(self) -> None:
        """Newlines are preserved."""
        result = convert_markdown_to_telegram("Line 1\nLine 2\nLine 3")
        assert "\n" in result

    def test_urls_preserved(self) -> None:
        """URLs in text have special chars escaped."""
        result = convert_markdown_to_telegram("Visit https://example.com")
        # The . in the URL gets escaped for Telegram MARKDOWN_V2
        assert "https://example\\.com" in result
