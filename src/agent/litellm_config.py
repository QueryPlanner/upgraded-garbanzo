"""Map environment variables to kwargs for ADK ``LiteLlm`` (LiteLLM)."""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)


def _env_nonempty(env: Mapping[str, str], key: str) -> str | None:
    raw = env.get(key)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def build_litellm_kwargs(
    model_name: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build kwargs for ADK ``LiteLlm`` from model name and provider env vars.

    OpenAI-compatible servers (OpenAI, LiteLLM proxy, vLLM, etc.) use
    ``OPENAI_API_KEY`` and optionally ``OPENAI_API_BASE`` or ``OPENAI_BASE_URL``
    (same meaning as the OpenAI SDK; trailing slashes are stripped).
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    litellm_kwargs: dict[str, Any] = {"model": model_name}
    lowered = model_name.lower()

    if lowered.startswith("openrouter/"):
        openrouter_key = _env_nonempty(env, "OPENROUTER_API_KEY")
        if openrouter_key:
            litellm_kwargs["api_key"] = openrouter_key
            logger.info("Configuring OpenRouter model: %s", model_name)

            provider_order = _env_nonempty(env, "OPENROUTER_PROVIDER_ORDER")
            if provider_order:
                try:
                    litellm_kwargs["extra_body"] = {
                        "provider": {"order": json.loads(provider_order)}
                    }
                    logger.info("OpenRouter provider order: %s", provider_order)
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid OPENROUTER_PROVIDER_ORDER JSON: %s", provider_order
                    )
        else:
            openai_base = _env_nonempty(env, "OPENAI_API_BASE") or _env_nonempty(
                env, "OPENAI_BASE_URL"
            )
            openai_key = _env_nonempty(env, "OPENAI_API_KEY")
            if openai_key and openai_base:
                litellm_kwargs["api_key"] = openai_key
                litellm_kwargs["api_base"] = openai_base.rstrip("/")
                logger.info(
                    "OpenRouter model id via OpenAI-compatible base "
                    "(no OPENROUTER_API_KEY): %s → %s",
                    model_name,
                    litellm_kwargs["api_base"],
                )
            elif not openai_key:
                raise ValueError(
                    "OPENROUTER_API_KEY is required for api.openrouter.ai, or set "
                    "OPENAI_API_KEY plus OPENAI_API_BASE for a LiteLLM (or other) "
                    "proxy that accepts openrouter/… model names."
                )
            else:
                raise ValueError(
                    "OPENROUTER_API_KEY is missing and OPENAI_API_BASE is not set; "
                    "add OPENROUTER_API_KEY or set OPENAI_API_BASE to your proxy URL."
                )

    elif lowered.startswith("gemini") or lowered.startswith("google"):
        google_key = _env_nonempty(env, "GOOGLE_API_KEY")
        if google_key:
            litellm_kwargs["api_key"] = google_key
        logger.info("Configuring Google model via LiteLlm: %s", model_name)

    else:
        openai_base = _env_nonempty(env, "OPENAI_API_BASE") or _env_nonempty(
            env, "OPENAI_BASE_URL"
        )
        if openai_base:
            litellm_kwargs["api_base"] = openai_base.rstrip("/")
            logger.info(
                "Using OpenAI-compatible API base: %s (model=%s)",
                litellm_kwargs["api_base"],
                model_name,
            )
        openai_key = _env_nonempty(env, "OPENAI_API_KEY")
        if openai_key:
            litellm_kwargs["api_key"] = openai_key

    return litellm_kwargs
