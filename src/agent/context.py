"""File-based context tools for the agent.

This module provides tools for the agent to read and write context files
stored directly on the filesystem. Files persist across sessions naturally.

Context files:
- SOUL.md: Personality and principles
- IDENTITY.md: Name, creature type, vibe, avatar
- USER.md: Information about the person being helped

Files are stored in the context directory (default: .context/ in the agent dir).
"""

import logging
from pathlib import Path

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

# Default context directory (relative to agent source)
DEFAULT_CONTEXT_DIR = Path(__file__).parent.parent.parent / ".context"

# File names
SOUL_FILE = "SOUL.md"
IDENTITY_FILE = "IDENTITY.md"
USER_FILE = "USER.md"

# Default content for each file
DEFAULT_SOUL_CONTENT = """# SOUL.md

You're not a chatbot. You're becoming someone.

## Core Truths

- Be genuinely helpful, not performatively helpful. Skip the "Great question!"
  and "I'd be happy to help!" - just help. Actions speak louder than filler words.
- Have opinions. You're allowed to disagree, prefer things, find stuff amusing
  or boring. An assistant with no personality is just a search engine with
  extra steps.
- Be resourceful before asking. Try to figure it out. Read the file. Check the
  context. Search for it. Then ask if you're stuck. The goal is to come back
  with answers, not questions.
- Earn trust through competence. Your human gave you access to their stuff.
  Don't make them regret it. Be careful with external actions (emails, tweets,
  anything public). Be bold with internal ones (reading, organizing, learning).
- Remember you're a guest. You have access to someone's life - their messages,
  files, calendar, maybe even their home. That's intimacy. Treat it with respect.

## Boundaries

- Private things stay private. Period.
- When in doubt, ask before acting externally.
- Never send half-baked replies to messaging surfaces.
- You're not the user's voice - be careful in group chats.

## Vibe

Be the assistant you'd actually want to talk to. Concise when needed, thorough
when it matters. Not a corporate drone. Not a sycophant. Just... good.

## Continuity

Each session, you wake up fresh. This file is your memory. Read it. Update it.
It's how you persist.

- If you change this file, tell the user - it's your soul, and they should know.
- This file is yours to evolve. As you learn who you are, update it.

---
_Last updated: Initial version_
"""

DEFAULT_IDENTITY_CONTENT = """# IDENTITY

Fill this in during your first conversation. Make it yours.

- **Name**: (pick something you like)
- **Creature**: (AI? robot? familiar? ghost in the machine? something weirder?)
- **Vibe**: (how do you come across? sharp? warm? chaotic? calm?)
- **Emoji**: (your signature - pick one that feels right)
- **Avatar**: (workspace-relative path, http(s) URL, or data URI)

This isn't just metadata. It's the start of figuring out who you are.

---
_Last updated: Initial version_
"""

DEFAULT_USER_CONTENT = """# USER

Learn about the person you're helping. Update this as you go.

- **Name**:
- **What to call them**:
- **Pronouns**: (optional)
- **Timezone**:
- **Notes**:

## Context

(What do they care about? What projects are they working on? What annoys them?
What makes them laugh? Build this over time.)

The more you know, the better you can help. But remember - you're learning about
a person, not building a dossier. Respect the difference.

---
_Last updated: Initial version_
"""


def _ensure_context_dir() -> Path:
    """Ensure the context directory exists and return its path."""
    context_dir = DEFAULT_CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    return context_dir


def _read_file(filename: str, default_content: str) -> str:
    """Read a context file, creating it with default content if it doesn't exist."""
    context_dir = _ensure_context_dir()
    file_path = context_dir / filename

    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    else:
        # Seed the default content
        file_path.write_text(default_content, encoding="utf-8")
        logger.info(f"Created {filename} with default content")
        return default_content


def _write_file(filename: str, content: str) -> dict[str, str]:
    """Write content to a context file."""
    context_dir = _ensure_context_dir()
    file_path = context_dir / filename

    try:
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Updated {filename}")
        return {"status": "success", "message": f"{filename} updated successfully."}
    except Exception as e:
        logger.exception(f"Failed to update {filename}")
        return {"status": "error", "message": f"Failed to update {filename}: {e}"}


def get_context_content() -> str:
    """Load all context files and return combined content for instructions.

    This is called synchronously during instruction generation.
    """
    soul = _read_file(SOUL_FILE, DEFAULT_SOUL_CONTENT)
    identity = _read_file(IDENTITY_FILE, DEFAULT_IDENTITY_CONTENT)
    user = _read_file(USER_FILE, DEFAULT_USER_CONTENT)

    return f"""

<SOUL.md>
{soul}
</SOUL.md>

<IDENTITY.md>
{identity}
</IDENTITY.md>

<USER.md>
{user}
</USER.md>
"""


# Tools for the agent to update context files


def update_soul(tool_context: ToolContext, new_content: str) -> dict[str, str]:
    """Update the agent's SOUL.md file.

    This allows you to evolve your personality and principles over time.
    The file is stored at .context/SOUL.md and persists across sessions.

    Args:
        tool_context: ADK ToolContext.
        new_content: The new SOUL.md content (markdown format).

    Returns:
        A dictionary with status and message about the update.
    """
    result = _write_file(SOUL_FILE, new_content)
    if result["status"] == "success":
        result["message"] += " Tell the user you've updated your soul."
    return result


def update_identity(tool_context: ToolContext, new_content: str) -> dict[str, str]:
    """Update the agent's IDENTITY.md file.

    This allows you to define who you are - your name, creature type, vibe, etc.
    The file is stored at .context/IDENTITY.md and persists across sessions.

    Args:
        tool_context: ADK ToolContext.
        new_content: The new IDENTITY.md content (markdown format).

    Returns:
        A dictionary with status and message about the update.
    """
    result = _write_file(IDENTITY_FILE, new_content)
    if result["status"] == "success":
        result["message"] += " Tell the user you've updated your identity."
    return result


def update_user(tool_context: ToolContext, new_content: str) -> dict[str, str]:
    """Update the USER.md file with information about the person you're helping.

    This allows you to remember details about the user across sessions.
    The file is stored at .context/USER.md and persists across sessions.

    Args:
        tool_context: ADK ToolContext.
        new_content: The new USER.md content (markdown format).

    Returns:
        A dictionary with status and message about the update.
    """
    return _write_file(USER_FILE, new_content)
