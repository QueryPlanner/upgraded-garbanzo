"""Session-state keys and constants for Telegram-specific agent settings.

Kept outside the ``telegram`` package so imports do not load ``telegram/__init__``
(which pulls in the bot and risks circular imports with ``agent.agent``).
"""

# ADK session state: full LiteLLM model id (e.g. openrouter/z-ai/glm-4.7).
TELEGRAM_SESSION_LITELLM_MODEL_KEY = "telegram_litellm_model"
# ADK session state: "openai" | "openrouter" (drives /model suggestions).
TELEGRAM_SESSION_PROVIDER_KEY = "telegram_litellm_provider"

# Cumulative LLM usage for the current session (Telegram sets user_id in state).
TELEGRAM_USAGE_PROMPT_KEY = "telegram_usage_prompt_tokens"
TELEGRAM_USAGE_COMPLETION_KEY = "telegram_usage_completion_tokens"
TELEGRAM_USAGE_TOTAL_KEY = "telegram_usage_total_tokens"
