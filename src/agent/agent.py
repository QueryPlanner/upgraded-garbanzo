"""ADK LlmAgent configuration."""

import logging
import os
from typing import Any

# Load environment variables BEFORE any other imports
# This ensures ROOT_AGENT_MODEL and API keys are available at module load time
from dotenv import load_dotenv

load_dotenv(override=True)

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.models import LiteLlm  # noqa: E402
from google.adk.plugins.global_instruction_plugin import (  # noqa: E402
    GlobalInstructionPlugin,
)
from google.adk.plugins.logging_plugin import LoggingPlugin  # noqa: E402
from google.adk.tools import LongRunningFunctionTool  # noqa: E402

from .callbacks import (  # noqa: E402
    LoggingCallbacks,
    add_memories_to_context,
    add_session_to_memory,
    notify_tool_call,
)
from .litellm_config import build_litellm_kwargs  # noqa: E402
from .litellm_session_router import TelegramLitellmRouter  # noqa: E402
from .mcp import create_mcp_toolsets  # noqa: E402
from .prompt import (  # noqa: E402
    return_description_root,
    return_global_instruction,
    return_instruction_root,
)
from .skills.loader import create_skill_toolset  # noqa: E402
from .telegram import TelegramLitellmRequestModelPlugin  # noqa: E402

# Mem0 memory integration (optional)
from .mem0 import is_mem0_enabled, save_memory, search_memory  # noqa: E402

__all__ = ["root_agent", "app"]
from .tools import (  # noqa: E402
    add_calories,
    brave_web_search,
    cancel_reminder,
    delete_context_file,
    delete_fitness_entry,
    docker_bash_execute,
    example_tool,
    get_calorie_stats,
    get_current_datetime,
    get_workout_stats,
    get_youtube_transcript,
    list_calories,
    list_context_files,
    list_reminders,
    list_workouts,
    log_workout,
    read_context_file,
    run_claude_coding_task,
    schedule_reminder,
    send_telegram_file,
    write_context_file,
)

logger = logging.getLogger(__name__)

logging_callbacks = LoggingCallbacks()

# Determine model configuration
model_name = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")
litellm_kwargs = build_litellm_kwargs(model_name)

# Create LiteLlm model (Telegram may override per chat via context var + session state)
logger.info(f"Creating LiteLlm with model: {model_name}")
_default_litellm = LiteLlm(**litellm_kwargs)
model = TelegramLitellmRouter.wrapping(_default_litellm)
logger.info("LiteLlm model created successfully (with Telegram per-session routing)")

# Create skill toolset for lazy-loading capabilities
skill_toolset = create_skill_toolset()
logger.info("Skill toolset created")
mcp_toolsets = create_mcp_toolsets()
logger.info("Created %s MCP toolset(s)", len(mcp_toolsets))

# Build base tools list
agent_tools: list[Any] = [
    # PreloadMemoryTool(),
    example_tool,
    brave_web_search,
    # Reminder tools
    get_current_datetime,
    schedule_reminder,
    list_reminders,
    cancel_reminder,
    # Fitness tracking tools
    add_calories,
    list_calories,
    get_calorie_stats,
    log_workout,
    list_workouts,
    get_workout_stats,
    delete_fitness_entry,
    # Context file tools (secure file operations)
    read_context_file,
    write_context_file,
    delete_context_file,
    list_context_files,
    # YouTube transcript tool
    get_youtube_transcript,
    # Docker-only shell (see docker_bash_execute docstring)
    docker_bash_execute,
    LongRunningFunctionTool(run_claude_coding_task),
    # Telegram: queue file for send after reply (see send_telegram_file)
    send_telegram_file,
    # Skills (lazy-loaded toolsets)
    skill_toolset,
    *mcp_toolsets,
]

# Conditionally add mem0 tools if configured
if is_mem0_enabled():
    logger.info("mem0 is enabled, adding memory tools")
    agent_tools.extend([save_memory, search_memory])
else:
    logger.info("mem0 is not configured, memory tools disabled")

# Build before_model_callback list with optional memory injection
before_model_callbacks: list[Any] = [logging_callbacks.before_model]
if is_mem0_enabled():
    logger.info("Adding memory injection callback")
    before_model_callbacks.append(add_memories_to_context)

root_agent = LlmAgent(
    name="garbanzo",
    description=return_description_root(),
    before_agent_callback=logging_callbacks.before_agent,
    after_agent_callback=[logging_callbacks.after_agent, add_session_to_memory],
    model=model,
    instruction=return_instruction_root,
    tools=agent_tools,
    before_model_callback=before_model_callbacks,
    after_model_callback=logging_callbacks.after_model,
    before_tool_callback=notify_tool_call,
    after_tool_callback=logging_callbacks.after_tool,
)

# Optional App configs explicitly set to None for template documentation
app = App(
    name="agent",
    root_agent=root_agent,
    plugins=[
        GlobalInstructionPlugin(return_global_instruction),
        # Before LoggingPlugin so ``LlmRequest.model`` matches Telegram override in logs
        TelegramLitellmRequestModelPlugin(),
        LoggingPlugin(),
    ],
    events_compaction_config=None,
    context_cache_config=None,
    resumability_config=None,
)
