"""Telegram slash-command model catalog and resolution."""

from __future__ import annotations

import os
from typing import Any, Literal

from .prefs import (
    TELEGRAM_SESSION_LITELLM_MODEL_KEY,
    TELEGRAM_SESSION_PROVIDER_KEY,
)

ProviderId = Literal["openai", "openrouter"]

OPENAI_MODELS: tuple[str, ...] = (
    "openai/glm-4.7",
    "openai/glm-5",
)

OPENROUTER_MODELS: tuple[str, ...] = (
    "openrouter/z-ai/glm-4.7",
    "openrouter/minimax/minimax-m2.7",
    "openrouter/moonshotai/kimi-k2.5",
    "openrouter/z-ai/glm-5",
)

PROVIDER_MODELS: dict[ProviderId, tuple[str, ...]] = {
    "openai": OPENAI_MODELS,
    "openrouter": OPENROUTER_MODELS,
}

# Single /model menu: OpenAI block then OpenRouter (1-based indices).
FLAT_MODEL_ENTRIES: tuple[tuple[ProviderId, str], ...] = tuple(
    [("openai", m) for m in OPENAI_MODELS]
    + [("openrouter", m) for m in OPENROUTER_MODELS]
)

_DISPLAY_ALIASES: dict[str, str] = {
    m: m.removeprefix("openrouter/") for m in OPENROUTER_MODELS
}


def default_root_model() -> str:
    """Same default as ``agent.agent`` when env is unset."""
    return os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash").strip()


def infer_provider_from_model_id(model_id: str) -> ProviderId | None:
    lowered = model_id.strip().lower()
    if lowered.startswith("openrouter/"):
        return "openrouter"
    if lowered.startswith("openai/"):
        return "openai"
    return None


def models_for_provider(provider: ProviderId) -> tuple[str, ...]:
    return PROVIDER_MODELS[provider]


def flat_menu_model_count() -> int:
    return len(FLAT_MODEL_ENTRIES)


def format_flat_model_menu() -> str:
    """Numbered list for /model (all providers)."""
    lines: list[str] = []
    for idx, (prov, full_id) in enumerate(FLAT_MODEL_ENTRIES, start=1):
        short = _DISPLAY_ALIASES.get(full_id, full_id)
        lines.append(f"{idx}. *{prov}* — `{short}` → `{full_id}`")
    return "\n".join(lines)


def resolve_flat_menu_index(one_based: int) -> tuple[str | None, str | None]:
    """Return ``(full_model_id, error_message)`` for a 1-based menu index."""
    if one_based < 1 or one_based > len(FLAT_MODEL_ENTRIES):
        n = len(FLAT_MODEL_ENTRIES)
        return None, f"Pick a number from 1 to {n} (send /model to see the list)."
    _prov, full_id = FLAT_MODEL_ENTRIES[one_based - 1]
    return full_id, None


def _strip_openrouter_prefix(s: str) -> str:
    return s.removeprefix("openrouter/").strip()


def resolve_model_argument(
    provider: ProviderId,
    arg: str,
) -> tuple[str | None, str | None]:
    """Return ``(full_model_id, error_message)`` for one provider (non-menu)."""
    raw = arg.strip()
    if not raw:
        return None, "Model name or index is required."

    if raw.isdigit():
        idx = int(raw)
        options = models_for_provider(provider)
        if idx < 1 or idx > len(options):
            return (
                None,
                f"Pick a number from 1 to {len(options)} for this provider.",
            )
        return options[idx - 1], None

    for full in models_for_provider(provider):
        if raw == full:
            return full, None

    if provider == "openrouter":
        suffix = _strip_openrouter_prefix(raw)
        normalized_suffix = suffix.removeprefix("/")
        for full in OPENROUTER_MODELS:
            rest = _strip_openrouter_prefix(full)
            if rest in (suffix, normalized_suffix):
                return full, None

    if provider == "openai":
        candidate = raw if "/" in raw else f"openai/{raw}"
        if candidate in OPENAI_MODELS:
            return candidate, None

    return None, f"Unknown model {raw!r} for provider {provider}."


def resolve_model_freeform(arg: str) -> tuple[str | None, str | None]:
    """Resolve a text model id by trying each provider (not used for plain digits)."""
    raw = arg.strip()
    if not raw:
        return None, "Send a model id or a number from /model."

    providers: tuple[ProviderId, ...] = ("openai", "openrouter")
    for prov in providers:
        full, _err = resolve_model_argument(prov, raw)
        if full is not None:
            return full, None

    return (
        None,
        f"Unknown model {raw!r}. Send /model for the numbered list.",
    )


def active_provider_for_session_state(state: dict[str, Any]) -> ProviderId:
    """Provider hint for session (used after picks; menu is flat now)."""
    raw = state.get(TELEGRAM_SESSION_PROVIDER_KEY)
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s == "openai":
            return "openai"
        if s == "openrouter":
            return "openrouter"

    mid = state.get(TELEGRAM_SESSION_LITELLM_MODEL_KEY)
    if isinstance(mid, str) and mid.strip():
        inferred = infer_provider_from_model_id(mid)
        if inferred is not None:
            return inferred

    env_inferred = infer_provider_from_model_id(default_root_model())
    if env_inferred is not None:
        return env_inferred

    return "openrouter"
