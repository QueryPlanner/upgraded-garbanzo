"""Tool modules for the ADK agent.

This package provides a compatibility layer that re-exports all public tool
symbols from domain-specific modules. Existing imports from `agent.tools`
continue to work without changes.

Domain tools are organized as follows:
- `reminders/tools.py` - Reminder scheduling tools
- `fitness/tools.py` - Fitness tracking tools
- `tools/brave_search.py` - Web search tool
- `tools/youtube.py` - YouTube transcript tool
- `tools/context_files.py` - Context file operations
- `tools/docker.py` - Docker bash execution
- `tools/telegram_files.py` - Telegram file sending
- `tools/claude_coding.py` - Claude coding tasks
- `tools/misc.py` - Example and datetime tools
"""

# Reminder tools
# Fitness tools
from ..fitness.tools import (
    add_calories,
    delete_fitness_entry,
    get_calorie_stats,
    get_workout_stats,
    list_calories,
    list_workouts,
    log_workout,
)
from ..reminders.tools import (
    SUPPORTED_RECURRENCE_MESSAGE,
    cancel_reminder,
    list_reminders,
    schedule_reminder,
)

# Cross-cutting tools
from .brave_search import brave_web_search
from .claude_coding import run_claude_coding_task
from .context_files import (
    delete_context_file,
    list_context_files,
    read_context_file,
    write_context_file,
)
from .docker import docker_bash_execute
from .misc import example_tool, get_current_datetime
from .telegram_files import send_telegram_file
from .youtube import get_youtube_transcript

__all__ = [
    # Reminder tools
    "SUPPORTED_RECURRENCE_MESSAGE",
    "cancel_reminder",
    "list_reminders",
    "schedule_reminder",
    # Fitness tools
    "add_calories",
    "delete_fitness_entry",
    "get_calorie_stats",
    "get_workout_stats",
    "list_calories",
    "list_workouts",
    "log_workout",
    # Cross-cutting tools
    "brave_web_search",
    "delete_context_file",
    "docker_bash_execute",
    "example_tool",
    "get_current_datetime",
    "get_youtube_transcript",
    "list_context_files",
    "read_context_file",
    "run_claude_coding_task",
    "send_telegram_file",
    "write_context_file",
]
