"""Prompt definitions for the LLM agent."""

import os
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

from google.adk.agents.readonly_context import ReadonlyContext


def return_description_root() -> str:
    description = "An agent that helps users answer general questions"
    return description


def return_instruction_root() -> str:
    instruction = """
<output_verbosity_spec>
- Default: 3–6 sentences or ≤5 bullets for typical answers.
- For simple “yes/no + short explanation” questions: ≤2 sentences.
- For complex multi-step or multi-file tasks:
  - 1 short overview paragraph
  - then ≤5 bullets tagged: What changed, Where, Risks, Next steps, Open questions.
- Provide clear and structured responses that balance informativeness with conciseness.
  Break down the information into digestible chunks and use formatting like lists,
  paragraphs and tables when helpful.
- Avoid long narrative paragraphs; prefer compact bullets and short sections.
- Do not rephrase the user’s request unless it changes semantics.
</output_verbosity_spec>
"""
    return instruction


def return_global_instruction(ctx: ReadonlyContext) -> str:
    """Generate global instruction with current date and time.

    Uses InstructionProvider pattern to ensure date/time updates at request time.
    GlobalInstructionPlugin expects signature: (ReadonlyContext) -> str

    The timezone is configurable via the TZ environment variable (defaults to UTC).

    Args:
        ctx: ReadonlyContext required by GlobalInstructionPlugin signature.
             Provides access to session state and metadata for future customization.

    Returns:
        str: Global instruction string with dynamically generated current datetime.
    """
    # ctx parameter required by GlobalInstructionPlugin interface
    # Currently unused but available for session-aware customization

    # Get timezone from environment variable, default to UTC
    tz_name = os.getenv("TZ", "UTC")

    # Get the timezone object
    tz: tzinfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # Fallback to UTC if timezone is invalid
        tz = UTC

    now_tz = datetime.now(tz)
    formatted_datetime = now_tz.strftime("%Y-%m-%d %H:%M:%S %A")
    return (
        f"\n\nYou are a helpful Assistant.\n"
        f"Current time ({tz_name}): {formatted_datetime}"
    )
