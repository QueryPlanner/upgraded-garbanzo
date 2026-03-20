"""Prompt definitions for the LLM agent."""

import logging
from datetime import datetime
from pathlib import Path

from google.adk.agents.readonly_context import ReadonlyContext

from .utils.app_timezone import get_app_timezone

logger = logging.getLogger(__name__)

# Default context directory (relative to this file's parent's parent = project root)
DEFAULT_CONTEXT_DIR = Path(__file__).parent.parent.parent / ".context"


def _load_context_file(filename: str, context_dir: Path | None = None) -> str:
    """Load a context file and return its content.

    Args:
        filename: Name of the context file (e.g., "IDENTITY.md").
        context_dir: Directory containing context files.
            Defaults to .context/ in project root.

    Returns:
        The file content, or empty string if file doesn't exist.
    """
    dir_path = context_dir or DEFAULT_CONTEXT_DIR
    file_path = dir_path / filename

    if not file_path.exists():
        logger.debug(f"Context file not found: {file_path}")
        return ""

    try:
        content = file_path.read_text(encoding="utf-8").strip()
        logger.debug(f"Loaded context file: {file_path}")
        return content
    except Exception as e:
        logger.warning(f"Failed to read context file {file_path}: {e}")
        return ""


def load_context(context_dir: Path | None = None) -> str:
    """Load all context files and combine them into a single instruction block.

    Args:
        context_dir: Directory containing context files.
            Defaults to .context/ in project root.

    Returns:
        Combined context string with all loaded files, or empty string if none found.
    """
    context_files = ["BOOTSTRAP.md", "IDENTITY.md", "SOUL.md", "USER.md"]
    parts: list[str] = []

    for filename in context_files:
        content = _load_context_file(filename, context_dir)
        if content:
            # Extract just the filename without extension for the section header
            section_name = Path(filename).stem
            parts.append(f"\n\n<{section_name}>\n{content}\n</{section_name}>")

    if parts:
        logger.info(f"Loaded {len(parts)} context file(s)")
    else:
        logger.warning("No context files loaded")

    return "".join(parts)


def return_description_root() -> str:
    description = "An agent that helps users answer general questions"
    return description


def return_instruction_root() -> str:
    # Load context files (identity, soul, user preferences)
    context = load_context()

    instruction = f"""{context}

<time_and_reminders>
- Default timezone is India Standard Time (Asia/Kolkata). Override with
  AGENT_TIMEZONE if needed.
- Before a relative reminder (e.g. \"in 10 minutes\"), call get_current_datetime
  first, then schedule_reminder with a relative phrase or the ISO time.
</time_and_reminders>

<output_verbosity_spec>
- Default: 3-6 sentences or 5 bullets or less for typical answers.
- For simple yes/no + short explanation questions: 2 sentences or less.
- For complex multi-step or multi-file tasks:
  - 1 short overview paragraph
  - then 5 bullets or less tagged: What changed, Where, Risks, Next steps.
- Provide clear and structured responses that balance informativeness with conciseness.
  Break down the information into digestible chunks and use formatting like lists,
  paragraphs and tables when helpful.
- Avoid long narrative paragraphs; prefer compact bullets and short sections.
- Do not rephrase the user's request unless it changes semantics.
</output_verbosity_spec>
"""
    return instruction


def return_global_instruction(ctx: ReadonlyContext) -> str:
    """Generate global instruction with current date and time.

    Uses InstructionProvider pattern to ensure date/time updates at request time.
    GlobalInstructionPlugin expects signature: (ReadonlyContext) -> str

    The timezone defaults to India Standard Time (Asia/Kolkata); override with
    AGENT_TIMEZONE (IANA name).

    Args:
        ctx: ReadonlyContext required by GlobalInstructionPlugin signature.
             Provides access to session state and metadata for future customization.

    Returns:
        str: Global instruction string with dynamically generated current datetime.
    """
    # ctx parameter required by GlobalInstructionPlugin interface
    # Currently unused but available for session-aware customization

    tz = get_app_timezone()
    tz_name = tz.key

    now_tz = datetime.now(tz)
    formatted_datetime = now_tz.strftime("%Y-%m-%d %H:%M:%S %A")
    return (
        f"\n\nYou are a helpful Assistant.\n"
        f"Current time ({tz_name}): {formatted_datetime}\n"
        "For reminders, call get_current_datetime before relative times like "
        "'in 5 minutes' so scheduling matches this clock."
    )
