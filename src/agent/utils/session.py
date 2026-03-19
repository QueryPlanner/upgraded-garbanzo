"""Session service factory for ADK runners.

Provides a shared way to create session services for both the FastAPI server
and the Telegram bot, using DATABASE_URL when set for persistent storage.
"""

import os
from pathlib import Path
from typing import Any

from google.adk.sessions.base_session_service import BaseSessionService


def create_session_service_for_runner(
    *,
    agents_dir: str | Path | None = None,
) -> BaseSessionService:
    """Create session service for an ADK runner (e.g., Telegram bot).

    Uses DATABASE_URL or AGENT_ENGINE when set for persistent storage.
    Otherwise returns in-memory session service.

    Args:
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

    database_url = os.getenv("DATABASE_URL")
    agent_engine = os.getenv("AGENT_ENGINE")

    has_persistent_session = bool(database_url or agent_engine)
    if not has_persistent_session:
        return InMemorySessionService()

    session_uri: str | None = None
    if database_url:
        session_uri = database_url.replace("sslmode=require", "ssl=require").replace(
            "&channel_binding=require", ""
        )
        if session_uri.startswith("postgresql://"):
            session_uri = session_uri.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
    elif agent_engine:
        session_uri = f"agentengine://{agent_engine}"

    if agents_dir is None:
        # Same default as server.py: parent of agent module
        agents_dir = os.getenv(
            "AGENT_DIR",
            str(Path(__file__).resolve().parent.parent.parent),
        )

    pool_pre_ping = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"
    pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "1800"))
    pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
    max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))

    session_db_kwargs: dict[str, Any] = {
        "pool_pre_ping": pool_pre_ping,
        "pool_recycle": pool_recycle,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
    }

    return create_session_service_from_options(
        base_dir=agents_dir,
        session_service_uri=session_uri,
        session_db_kwargs=session_db_kwargs,
        use_local_storage=False,
    )
