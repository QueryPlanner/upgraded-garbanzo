"""Markdown to Telegram MARKDOWN_V2 converter.

This module converts standard markdown (as output by LLMs) to Telegram's
MARKDOWN_V2 format, which requires escaping special characters and has
different syntax rules.

Telegram MARKDOWN_V2 syntax:
- *bold*
- _italic_
- __underline__
- ~strikethrough~
- ||spoiler||
- `inline code`
- ```code block```
- [link](url)

Special characters that MUST be escaped outside code blocks:
_ * [ ] ( ) ~ ` > # + - = | { } . !

The strategy:
1. Parse and protect code blocks and inline code (no escaping inside)
2. Identify formatting spans (bold, italic, links, etc.) and protect them
3. Escape special characters in regular text
4. Reconstruct with Telegram formatting
"""

import re
from dataclasses import dataclass
from enum import Enum, auto


class SegmentType(Enum):
    """Type of text segment."""

    CODE_BLOCK = auto()
    INLINE_CODE = auto()
    BOLD = auto()
    ITALIC = auto()
    UNDERLINE = auto()
    STRIKETHROUGH = auto()
    LINK = auto()
    REGULAR = auto()


@dataclass
class Segment:
    """A segment of text with its type and content."""

    text: str
    segment_type: SegmentType
    # For links, store the display text and URL separately
    link_text: str | None = None
    link_url: str | None = None


# Characters that must be escaped in Telegram MARKDOWN_V2
# (outside of code blocks and inline code)
SPECIAL_CHARS = set("_*[]()~`>#+-=|{}.!")


def _find_formatting_spans(text: str) -> list[Segment]:
    """Find all formatting spans in text, returning them in order.

    This identifies bold, italic, underline, strikethrough, links, and code.
    Overlapping spans are handled by priority: code > links > formatting.

    Args:
        text: Input text to parse.

    Returns:
        List of segments covering the entire text in order.
    """
    # Track protected regions (code blocks, inline code)
    protected: list[tuple[int, int, SegmentType]] = []

    # Find code blocks first (highest priority)
    for match in re.finditer(r"```[\s\S]*?```", text):
        protected.append((match.start(), match.end(), SegmentType.CODE_BLOCK))

    # Find inline code (not inside code blocks)
    for match in re.finditer(r"`[^`]+`", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.INLINE_CODE))

    # Find links [text](url) - not inside protected regions
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.LINK))

    # Find bold **text** - not inside protected regions
    for match in re.finditer(r"\*\*([^*]+)\*\*", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.BOLD))

    # Find underline __text__ (markdown: bold, Telegram: underline)
    for match in re.finditer(r"__([^_]+)__", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.UNDERLINE))

    # Find strikethrough ~~text~~
    for match in re.finditer(r"~~([^~]+)~~", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.STRIKETHROUGH))

    # Find italic *text* (single asterisk, not double)
    # Must not be adjacent to another *
    for match in re.finditer(r"(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.ITALIC))

    # Find italic _text_ (single underscore, not double)
    for match in re.finditer(r"(?<!_)_(?!_)([^_]+)(?<!_)_(?!_)", text):
        start, end = match.start(), match.end()
        if not any(ps <= start and end <= pe for ps, pe, _ in protected):
            protected.append((start, end, SegmentType.ITALIC))

    # Sort by start position
    protected.sort(key=lambda x: x[0])

    # Remove overlaps (keep earlier spans)
    non_overlapping: list[tuple[int, int, SegmentType]] = []
    for start, end, seg_type in protected:
        if not any(ps < end and start < pe for ps, pe, _ in non_overlapping):
            non_overlapping.append((start, end, seg_type))

    non_overlapping.sort(key=lambda x: x[0])

    # Build segments covering the entire text
    segments: list[Segment] = []
    last_end = 0

    for start, end, seg_type in non_overlapping:
        # Add regular text before this segment
        if start > last_end:
            segments.append(Segment(text[last_end:start], SegmentType.REGULAR))

        # Add the formatted segment
        segment_text = text[start:end]

        if seg_type == SegmentType.LINK:
            # Extract link text and URL
            link_match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", segment_text)
            if link_match:
                segments.append(
                    Segment(
                        text=segment_text,
                        segment_type=SegmentType.LINK,
                        link_text=link_match.group(1),
                        link_url=link_match.group(2),
                    )
                )
        elif seg_type == SegmentType.BOLD:
            # Extract inner content
            inner = re.match(r"\*\*([^*]+)\*\*", segment_text)
            if inner:
                segments.append(
                    Segment(text=inner.group(1), segment_type=SegmentType.BOLD)
                )
        elif seg_type == SegmentType.ITALIC:
            # Extract inner content
            inner = re.match(r"(?<![*_])([*_])([^*_]+)\1(?![*_])", segment_text)
            if inner:
                segments.append(
                    Segment(text=inner.group(2), segment_type=SegmentType.ITALIC)
                )
        elif seg_type == SegmentType.UNDERLINE:
            inner = re.match(r"__([^_]+)__", segment_text)
            if inner:
                segments.append(
                    Segment(text=inner.group(1), segment_type=SegmentType.UNDERLINE)
                )
        elif seg_type == SegmentType.STRIKETHROUGH:
            inner = re.match(r"~~([^~]+)~~", segment_text)
            if inner:
                segments.append(
                    Segment(text=inner.group(1), segment_type=SegmentType.STRIKETHROUGH)
                )
        else:
            segments.append(Segment(text=segment_text, segment_type=seg_type))

        last_end = end

    # Add remaining regular text
    if last_end < len(text):
        segments.append(Segment(text[last_end:], SegmentType.REGULAR))

    return segments if segments else [Segment(text, SegmentType.REGULAR)]


def _escape_special_chars(text: str) -> str:
    """Escape special characters for Telegram MARKDOWN_V2.

    Args:
        text: Input text (regular text, not formatted).

    Returns:
        Text with special characters escaped.
    """
    result = []
    for char in text:
        if char in SPECIAL_CHARS:
            result.append(f"\\{char}")
        else:
            result.append(char)
    return "".join(result)


def _segment_to_telegram(segment: Segment) -> str:
    """Convert a segment to Telegram MARKDOWN_V2 format.

    Args:
        segment: The segment to convert.

    Returns:
        Telegram-formatted text.
    """
    if segment.segment_type == SegmentType.CODE_BLOCK:
        # Code blocks are preserved as-is
        return segment.text

    if segment.segment_type == SegmentType.INLINE_CODE:
        # Inline code is preserved as-is
        return segment.text

    if segment.segment_type == SegmentType.LINK:
        # Link format: [text](url) - escape special chars in text only
        if segment.link_text is not None and segment.link_url is not None:
            escaped_text = _escape_special_chars(segment.link_text)
            return f"[{escaped_text}]({segment.link_url})"
        return segment.text

    if segment.segment_type == SegmentType.BOLD:
        # Telegram bold: *text*
        escaped = _escape_special_chars(segment.text)
        return f"*{escaped}*"

    if segment.segment_type == SegmentType.ITALIC:
        # Telegram italic: _text_
        escaped = _escape_special_chars(segment.text)
        return f"_{escaped}_"

    if segment.segment_type == SegmentType.UNDERLINE:
        # Telegram underline: __text__
        escaped = _escape_special_chars(segment.text)
        return f"__{escaped}__"

    if segment.segment_type == SegmentType.STRIKETHROUGH:
        # Telegram strikethrough: ~text~
        escaped = _escape_special_chars(segment.text)
        return f"~{escaped}~"

    # Regular text - just escape
    return _escape_special_chars(segment.text)


def convert_markdown_to_telegram(text: str) -> str:
    """Convert standard markdown to Telegram MARKDOWN_V2 format.

    This function:
    1. Preserves code blocks and inline code exactly
    2. Converts markdown syntax to Telegram format
    3. Escapes special characters in regular text

    Args:
        text: Markdown text from the agent.

    Returns:
        Text formatted for Telegram MARKDOWN_V2.
    """
    if not text:
        return text

    # Find all formatting spans
    segments = _find_formatting_spans(text)

    # Convert each segment to Telegram format
    result_parts = [_segment_to_telegram(seg) for seg in segments]

    return "".join(result_parts)


def validate_telegram_markup(text: str) -> bool:
    """Validate that Telegram MARKDOWN_V2 markup has balanced entities.

    Checks bold (*), italic (_), underline (__), strikethrough (~), inline
    code (`), and fenced code blocks (```). Does not parse links
    ([text](url)) or spoiler (||) spans.

    Args:
        text: Text in Telegram MARKDOWN_V2 format.

    Returns:
        True if markup is valid/balanced, False if there are unclosed entities.
    """
    # Track open/close states for each formatting type
    # We need to parse the text considering escape sequences

    i = 0
    bold_open = False
    italic_open = False
    underline_open = False
    strike_open = False
    code_open = False
    code_block_open = False

    while i < len(text):
        char = text[i]

        # Check for escape sequence - skip the escaped char
        if char == "\\" and i + 1 < len(text):
            i += 2
            continue

        # Check for code blocks (triple backtick)
        if text[i : i + 3] == "```":
            code_block_open = not code_block_open
            i += 3
            continue

        # Skip processing if inside code block
        if code_block_open:
            i += 1
            continue

        # Check for inline code (single backtick)
        if char == "`":
            code_open = not code_open
            i += 1
            continue

        # Skip processing if inside inline code
        if code_open:
            i += 1
            continue

        # Check for underline (double underscore)
        if text[i : i + 2] == "__":
            underline_open = not underline_open
            i += 2
            continue

        # Single underscore (italic); double underscore handled above
        if char == "_":
            italic_open = not italic_open
            i += 1
            continue

        # Strikethrough uses single tilde in Telegram MARKDOWN_V2 (~text~)
        if char == "~":
            strike_open = not strike_open
            i += 1
            continue

        # Check for bold (single asterisk in Telegram MARKDOWN_V2)
        # Note: In Telegram MARKDOWN_V2, *text* is bold, _text_ is italic
        if char == "*":
            bold_open = not bold_open
            i += 1
            continue

        i += 1

    # All entities should be closed
    return not (
        bold_open
        or italic_open
        or underline_open
        or strike_open
        or code_open
        or code_block_open
    )
