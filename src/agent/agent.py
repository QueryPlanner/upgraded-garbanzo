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
from google.adk.tools.preload_memory_tool import PreloadMemoryTool  # noqa: E402

from .callbacks import (  # noqa: E402
    LoggingCallbacks,
    add_session_to_memory,
    notify_tool_call,
)
from .prompt import (  # noqa: E402
    return_description_root,
    return_global_instruction,
    return_instruction_root,
)
from .skills.loader import create_skill_toolset  # noqa: E402
from .tools import (  # noqa: E402
    add_calories,
    cancel_reminder,
    delete_fitness_entry,
    example_tool,
    get_calorie_stats,
    get_workout_stats,
    get_youtube_transcript,
    list_calories,
    list_context_files,
    list_reminders,
    list_workouts,
    log_workout,
    read_context_file,
    schedule_reminder,
    write_context_file,
)

logger = logging.getLogger(__name__)

logging_callbacks = LoggingCallbacks()

# Determine model configuration
model_name = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

# Build LiteLlm model configuration
# LiteLlm is used for all models to support OpenRouter and other providers
litellm_kwargs: dict[str, Any] = {"model": model_name}

# Configure API key based on provider
if model_name.lower().startswith("openrouter/"):
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise ValueError(
            "OPENROUTER_API_KEY environment variable is required for OpenRouter models"
        )
    litellm_kwargs["api_key"] = openrouter_key
    logger.info(f"Configuring OpenRouter model: {model_name}")

    # Provider enforcement for OpenRouter models
    # OpenRouter can serve some models through multiple providers with varying
    # quality/cost. Use OPENROUTER_PROVIDER_ORDER env var to specify preference.
    # Example: OPENROUTER_PROVIDER_ORDER='["google-vertex", "together"]'
    # See: https://openrouter.ai/docs/provider-routing
    provider_order = os.getenv("OPENROUTER_PROVIDER_ORDER")
    if provider_order:
        import json

        try:
            litellm_kwargs["extra_body"] = {
                "provider": {"order": json.loads(provider_order)}
            }
            logger.info(f"OpenRouter provider order: {provider_order}")
        except json.JSONDecodeError:
            logger.warning(f"Invalid OPENROUTER_PROVIDER_ORDER JSON: {provider_order}")

elif model_name.lower().startswith("gemini") or model_name.lower().startswith("google"):
    # For Google models, we can use either GOOGLE_API_KEY or the default
    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key:
        litellm_kwargs["api_key"] = google_key
    logger.info(f"Configuring Google model via LiteLlm: {model_name}")

# Create LiteLlm model
logger.info(f"Creating LiteLlm with model: {model_name}")
model = LiteLlm(**litellm_kwargs)
logger.info("LiteLlm model created successfully")

# Create skill toolset for lazy-loading capabilities
skill_toolset = create_skill_toolset()
logger.info("Skill toolset created")

root_agent = LlmAgent(
    name="root_agent",
    description=return_description_root(),
    before_agent_callback=logging_callbacks.before_agent,
    after_agent_callback=[logging_callbacks.after_agent, add_session_to_memory],
    model=model,
    instruction=return_instruction_root(),
    tools=[
        PreloadMemoryTool(),
        example_tool,
        # Reminder tools
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
        list_context_files,
        # YouTube transcript tool
        get_youtube_transcript,
        # Skills (lazy-loaded toolsets)
        skill_toolset,
    ],
    before_model_callback=logging_callbacks.before_model,
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
        LoggingPlugin(),
    ],
    events_compaction_config=None,
    context_cache_config=None,
    resumability_config=None,
)
