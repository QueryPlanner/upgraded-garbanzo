"""Session service factory for ADK runners.

Provides a shared way to create session services for both the FastAPI server
and the Telegram bot, using DATABASE_URL when set for persistent storage.
Set ADK_USE_DATABASE_SESSION=false to keep DATABASE_URL for app tables only
(reminders, fitness) while using in-memory ADK sessions.
"""

import os
from pathlib import Path

from google.adk.sessions.base_session_service import BaseSessionService

from .config import SessionConfig


def create_session_service_for_runner(
    *,
    config: SessionConfig | None = None,
    agents_dir: str | Path | None = None,
) -> BaseSessionService:
    """Create session service for an ADK runner (e.g., Telegram bot).

    Uses DATABASE_URL or AGENT_ENGINE when set for persistent storage, unless
    ADK_USE_DATABASE_SESSION is false (in-memory only; DATABASE_URL unchanged
    for other features). Otherwise returns in-memory session service.

    Args:
        config: SessionConfig instance with validated configuration. If None,
            creates one from environment variables.
        agents_dir: Base directory for agents. Defaults to parent of agent
            module (same as server's AGENT_DIR).

    Returns:
        Configured BaseSessionService instance.
    """
    from google.adk.cli.utils.service_factory import (
        create_session_service_from_options,
    )
    from google.adk.sessions.in_memory_session_service import (
        InMemorySessionService,
    )

    if config is None:
        config = SessionConfig.model_validate(os.environ)

    if not config.adk_use_database_session:
        return InMemorySessionService()

    # Use in-memory sessions when no persistent storage is configured
    session_uri = config.asyncpg_session_uri
    if not session_uri:
        return InMemorySessionService()

    if agents_dir is None:
        # Same default as server.py: parent of agent module
        agents_dir = os.getenv(
            "AGENT_DIR",
            str(Path(__file__).resolve().parent.parent.parent),
        )

    return create_session_service_from_options(
        base_dir=agents_dir,
        session_service_uri=session_uri,
        session_db_kwargs=config.session_db_kwargs,
        use_local_storage=False,
    )
