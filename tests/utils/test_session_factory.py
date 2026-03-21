"""Tests for ADK session service factory."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from google.adk.sessions.in_memory_session_service import InMemorySessionService

from agent.utils.config import SessionConfig
from agent.utils.session import create_session_service_for_runner


class TestCreateSessionServiceForRunner:
    """Tests for create_session_service_for_runner function."""

    def test_in_memory_sessions_when_adk_database_disabled(self) -> None:
        """ADK_USE_DATABASE_SESSION=false skips Postgres for sessions.

        Configuration still resolves the database settings.
        """
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

    def test_in_memory_when_no_database_url(self) -> None:
        """Returns InMemorySessionService when DATABASE_URL is not set."""
        cfg = SessionConfig.model_validate(
            {
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )
        assert cfg.adk_use_database_session is True
        assert cfg.database_url is None

        service = create_session_service_for_runner(config=cfg)
        assert isinstance(service, InMemorySessionService)

    def test_in_memory_when_session_uri_is_none(self) -> None:
        """Returns InMemorySessionService when session_uri resolves to None."""
        cfg = SessionConfig.model_validate(
            {
                "DATABASE_URL": "",  # Empty string
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )
        assert cfg.adk_use_database_session is True

        service = create_session_service_for_runner(config=cfg)
        assert isinstance(service, InMemorySessionService)

    def test_creates_database_session_service_with_agents_dir_default(self) -> None:
        """Create the DB session service with the default agents dir.

        This path is used when ADK_USE_DATABASE_SESSION is true.
        """
        cfg = SessionConfig.model_validate(
            {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/appdb",
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )

        mock_service = MagicMock()
        with patch(
            "google.adk.cli.utils.service_factory.create_session_service_from_options",
            return_value=mock_service,
        ) as mock_create:
            service = create_session_service_for_runner(config=cfg)

            assert service is mock_service
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["use_local_storage"] is False
            assert call_kwargs["session_service_uri"] == cfg.asyncpg_session_uri

    def test_creates_database_session_service_with_custom_agents_dir(self) -> None:
        """Creates database session service with custom agents_dir."""
        cfg = SessionConfig.model_validate(
            {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/appdb",
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )
        custom_dir = Path("/custom/agents")

        mock_service = MagicMock()
        with patch(
            "google.adk.cli.utils.service_factory.create_session_service_from_options",
            return_value=mock_service,
        ) as mock_create:
            service = create_session_service_for_runner(
                config=cfg, agents_dir=custom_dir
            )

            assert service is mock_service
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["base_dir"] == custom_dir

    def test_uses_agent_dir_env_var_for_default_agents_dir(self) -> None:
        """Uses AGENT_DIR environment variable for default agents_dir."""
        cfg = SessionConfig.model_validate(
            {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/appdb",
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )
        custom_agent_dir = "/custom/agent/dir"

        mock_service = MagicMock()
        with (
            patch(
                "google.adk.cli.utils.service_factory.create_session_service_from_options",
                return_value=mock_service,
            ) as mock_create,
            patch.dict("os.environ", {"AGENT_DIR": custom_agent_dir}),
        ):
            service = create_session_service_for_runner(config=cfg)

            assert service is mock_service
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["base_dir"] == custom_agent_dir

    def test_creates_service_without_config_uses_env(self) -> None:
        """Creates service from environment when config is None."""
        mock_service = MagicMock()
        with (
            patch(
                "google.adk.cli.utils.service_factory.create_session_service_from_options",
                return_value=mock_service,
            ),
            patch.dict("os.environ", {"DATABASE_URL": ""}),
        ):
            # When DATABASE_URL is empty/not set, returns InMemorySessionService
            service = create_session_service_for_runner(config=None)
            assert isinstance(service, InMemorySessionService)
