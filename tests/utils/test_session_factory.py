"""Tests for ADK session service factory."""

from google.adk.sessions.in_memory_session_service import InMemorySessionService

from agent.utils.config import SessionConfig
from agent.utils.session import create_session_service_for_runner


def test_in_memory_sessions_when_adk_database_disabled() -> None:
    """ADK_USE_DATABASE_SESSION=false skips Postgres for sessions, not for config."""
    cfg = SessionConfig.model_validate(
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/appdb?ssl=require",
            "ADK_USE_DATABASE_SESSION": "false",
        }
    )
    assert cfg.adk_use_database_session is False
    assert cfg.effective_asyncpg_dsn is not None

    service = create_session_service_for_runner(config=cfg)
    assert isinstance(service, InMemorySessionService)
