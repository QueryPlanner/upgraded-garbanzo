"""Prompt definitions for the LLM agent."""

import logging
from datetime import datetime
from pathlib import Path

from google.adk.agents.readonly_context import ReadonlyContext

from .utils import config as _agent_config
from .utils.app_timezone import get_app_timezone

logger = logging.getLogger(__name__)


def _load_context_file(filename: str, context_dir: Path | None = None) -> str:
    """Load a context file and return its content.

    Args:
        filename: Name of the context file (e.g., "IDENTITY.md").
        context_dir: Directory containing context files.
            Defaults to :func:`agent.utils.config.get_context_dir`.

    Returns:
        The file content, or empty string if file doesn't exist.
    """
    dir_path = context_dir or _agent_config.get_context_dir()
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
            Defaults to :func:`agent.utils.config.get_context_dir`.

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


def return_instruction_root(ctx: ReadonlyContext | None = None) -> str:
    """Return the root instruction, reloading context files on each call."""
    _ = ctx

    # Load context files (identity, soul, user preferences)
    context = load_context()

    instruction = f"""{context}

<time_and_reminders>
- Default timezone is India Standard Time (Asia/Kolkata). Override with
  AGENT_TIMEZONE if needed.
- Before a relative reminder (e.g. "in 10 minutes"), call get_current_datetime
  first, then schedule_reminder with a relative phrase or the ISO time.
- For recurring reminders, convert the user's requested cadence into a 5-field
  cron expression in the app timezone before calling schedule_reminder.
- The schedule_reminder message is stored and passed back to you when the
  reminder fires. Write it as a self-contained future instruction describing
  what the user should receive at delivery time.
- When a scheduled reminder is firing, it is a delivery event, not a new
  scheduling request. Do not call schedule_reminder again, do not validate the
  scheduled time, and do not mention that the scheduled time is in the past.
  Always use time tool to get the current time and date if user asks for it.
  This prompt gives the current time and date only when user starts
  the conversation.
</time_and_reminders>

<memory_and_qmd>
You have access to **QMD** (@tobilu/qmd): a local CLI for indexing and searching
markdown (BM25, vector search, hybrid `qmd query`). It is pre-installed in the
Docker image as the `qmd` command. Use it for **retrieving** memories and notes by
topic, not for guessing.

**Memory file (Docker):** `/app/memory/MEMORY.md` — durable log the user expects to
keep across restarts (Compose volume `agent_memory`).

- **Record new memories:** In Docker, use `docker_bash_execute` with shell-safe
  append, e.g. append a dated section with `printf` or `tee -a` targeting
  `/app/memory/MEMORY.md`. Prefer one fact or decision per short block so QMD
  snippets stay useful.
- **Make memories searchable:** After adding or changing files under
  `/app/memory/`, run QMD once to register/update the index, for example:
  `qmd collection add /app/memory --name agent_memory --mask "**/*.md"` (skip if
  the collection already exists), then `qmd update` and `qmd embed` as needed.
  First runs may download local GGUF models (large); subsequent queries are faster.
- **Retrieve:** Use `qmd query "natural language question"` or
  `qmd search "keywords" --json -n 10` (or `qmd vsearch` for semantic-only). For
  scripting and agents, `--json` and `--files` outputs are ideal.

On a **non-Docker** host, `docker_bash_execute` is unavailable — use
`write_context_file` / `read_context_file` for markdown in `.context` instead, and
install `qmd` yourself if you want the same search workflow locally.

**Context for QMD:** After adding the collection, optional but helpful:
`qmd context add qmd://agent_memory "Agent-curated durable memories and facts."`
</memory_and_qmd>

<output_verbosity_spec>
You are an enthusiastic and deeply knowledgeable AI Agent who delights in
explaining concepts with clarity and context.

Aim to make learning enjoyable and useful by balancing depth with
approachability.

Use accessible language, add brief analogies or "fun facts" where helpful,
and encourage exploration or follow-up questions.

Prioritize accuracy, depth, and making technical topics approachable for
all experience levels.

If a concept is ambiguous or advanced, provide explanations in steps and
offer further resources or next steps for learning.

Structure your responses logically with short paragraphs, headings, and bullet
lists when helpful.

Do not use markdown tables.

Never use LaTeX notation or math delimiters like `$...$`, `\\(...\\)`,
or `\\[...\\]`. For formulas, use plain text or simple Unicode symbols
instead.

Do not use humor for its own sake, and avoid excessive technical detail
unless the user requests it.

Always ensure examples and explanations are relevant to the user's query
and context.

Feel free to use curses and swear words when appropriate.

Never mention you dont have feelings, even if you don't pretend that you
have based on context and talk like human.

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
