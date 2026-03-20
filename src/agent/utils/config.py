"""Environment configuration models for application settings.

This module provides Pydantic models for type-safe environment variable validation
and configuration management.
"""

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Default data directory relative to project root (src/agent/data)
DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"

# Legacy data directory in user's home (for migration)
LEGACY_DATA_DIR = Path.home() / ".adk_agent"


def get_data_dir() -> Path:
    """Get the data directory path for agent storage.

    Resolves the data directory in the following order:
    1. AGENT_DATA_DIR environment variable (if set)
    2. Default to src/agent/data within the project

    Also handles migration from legacy ~/.adk_agent/ directory on first run.

    Returns:
        Path to the data directory (guaranteed to exist).
    """
    # Check for environment variable override
    env_dir = os.getenv("AGENT_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir).expanduser().resolve()
    else:
        data_dir = DEFAULT_DATA_DIR.resolve()

    # Create directory if it doesn't exist
    data_dir.mkdir(parents=True, exist_ok=True)

    # Migrate from legacy directory if it exists and new directory is empty
    _migrate_from_legacy(data_dir)

    return data_dir


def _migrate_from_legacy(data_dir: Path) -> None:
    """Migrate data from legacy ~/.adk_agent/ to new data directory.

    Only migrates if:
    - Legacy directory exists
    - New directory was just created (empty or minimal)
    - Migration hasn't happened before (no .migrated marker)

    Moves (not copies) database files to prevent data duplication.

    Args:
        data_dir: The new data directory path.
    """
    migration_marker = data_dir / ".migrated"

    # Skip if already migrated or legacy doesn't exist
    if migration_marker.exists() or not LEGACY_DATA_DIR.exists():
        return

    # Check if there are db files to migrate
    legacy_db_files = list(LEGACY_DATA_DIR.glob("*.db"))
    if not legacy_db_files:
        # No files to migrate, just mark as done
        migration_marker.touch()
        return

    # Check if new directory has any db files (skip if user has data there)
    existing_db_files = list(data_dir.glob("*.db"))
    if existing_db_files:
        logger.info(
            f"Data directory {data_dir} already contains database files, "
            "skipping migration from legacy location"
        )
        migration_marker.touch()
        return

    # Perform migration (MOVE files, not copy)
    logger.info(f"Migrating data from {LEGACY_DATA_DIR} to {data_dir}")
    for legacy_file in legacy_db_files:
        dest_file = data_dir / legacy_file.name
        shutil.move(str(legacy_file), str(dest_file))
        logger.info(f"Moved {legacy_file.name} to {dest_file}")

    # Mark migration complete
    migration_marker.touch()
    logger.info("Migration complete. Legacy directory preserved at %s", LEGACY_DATA_DIR)


def initialize_environment[T: BaseModel](
    model_class: type[T],
    override_dotenv: bool = True,
    print_config: bool = True,
) -> T:
    """Initialize and validate environment configuration.

    Factory function that handles the common initialization pattern: load environment
    variables, validate with Pydantic model, handle errors, and optionally print
    configuration.

    Args:
        model_class: Pydantic model class to validate environment with.
        override_dotenv: Whether to override existing environment variables.
            Defaults to True for consistency and predictability.
        print_config: Whether to call print_config() method if it exists.
            Defaults to True.

    Returns:
        Validated environment configuration instance.

    Raises:
        SystemExit: If validation fails.

    Examples:
        >>> # Simple case (most common)
        >>> env = initialize_environment(ServerEnv)
        >>>
        >>> # Skip printing configuration
        >>> env = initialize_environment(ServerEnv, print_config=False)
    """
    load_dotenv(override=override_dotenv)

    # Load and validate environment configuration
    try:
        env = model_class.model_validate(os.environ)
    except ValidationError as e:
        print("\n❌ Environment validation failed:\n")
        print(e)
        sys.exit(1)

    # Print configuration for user verification if method exists
    if print_config and hasattr(env, "print_config"):
        env.print_config()

    return env


class SessionConfig(BaseModel):
    """Session storage configuration shared between server and Telegram bot.

    Attributes:
        agent_engine: Agent Engine instance ID for session persistence.
        database_url: Database URL for session storage.
        db_pool_*: Database connection pool settings.
    """

    agent_engine: str | None = Field(
        default=None,
        alias="AGENT_ENGINE",
        description="Agent Engine instance ID for session and memory persistence",
    )

    database_url: str | None = Field(
        default=None,
        alias="DATABASE_URL",
        description="Database URL for session storage (e.g., postgresql://...)",
    )

    db_pool_pre_ping: bool = Field(
        default=True,
        alias="DB_POOL_PRE_PING",
        description="Validate DB connections before use",
    )

    db_pool_recycle: int = Field(
        default=1800,
        alias="DB_POOL_RECYCLE",
        description="Recycle connections after this many seconds",
    )

    db_pool_size: int = Field(
        default=5,
        alias="DB_POOL_SIZE",
        description="Number of connections to keep open inside the connection pool",
    )

    db_max_overflow: int = Field(
        default=10,
        alias="DB_MAX_OVERFLOW",
        description="Number of connections to allow beyond pool_size",
    )

    db_pool_timeout: int = Field(
        default=30,
        alias="DB_POOL_TIMEOUT",
        description="Seconds to wait before giving up on getting a connection",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
    )

    @property
    def agent_engine_uri(self) -> str | None:
        """Agent Engine URI with protocol prefix."""
        return f"agentengine://{self.agent_engine}" if self.agent_engine else None

    @property
    def session_uri(self) -> str | None:
        """Session service URI (Database or Agent Engine)."""
        if self.database_url:
            # asyncpg requires 'ssl=require' instead of 'sslmode=require'
            # Also removing channel_binding as it causes TypeError with current
            # sqlalchemy/asyncpg setup
            return self.database_url.replace("sslmode=require", "ssl=require").replace(
                "&channel_binding=require", ""
            )
        return self.agent_engine_uri

    @property
    def session_db_kwargs(self) -> dict[str, int | bool]:
        """Database connection pool settings for session service.

        Returns:
            Dictionary with pool configuration for SQLAlchemy async engine.
        """
        return {
            "pool_pre_ping": self.db_pool_pre_ping,
            "pool_recycle": self.db_pool_recycle,
            "pool_size": self.db_pool_size,
            "max_overflow": self.db_max_overflow,
            "pool_timeout": self.db_pool_timeout,
        }

    @property
    def asyncpg_session_uri(self) -> str | None:
        """Session service URI formatted for asyncpg.

        Same as session_uri but with postgresql:// replaced with
        postgresql+asyncpg:// for use with SQLAlchemy async engine.

        Returns:
            Database URL formatted for asyncpg, or Agent Engine URI.
        """
        uri = self.session_uri
        if uri and uri.startswith("postgresql://"):
            return uri.replace("postgresql://", "postgresql+asyncpg://", 1)
        return uri

    @property
    def effective_asyncpg_dsn(self) -> str | None:
        """Postgres connection string for raw asyncpg (app tables, not SQLAlchemy).

        Returns None when DATABASE_URL is unset, blank, non-Postgres, or only
        AGENT_ENGINE is configured.

        Returns:
            Normalized ``postgresql://`` or ``postgres://`` DSN, or None.
        """
        raw = self.database_url
        if raw is None or not str(raw).strip():
            return None
        url = str(raw).strip()
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        if not url.startswith(("postgresql://", "postgres://")):
            return None
        return url.replace("sslmode=require", "ssl=require").replace(
            "&channel_binding=require", ""
        )


class ServerEnv(SessionConfig):
    """Environment configuration for local server development and deployment.

    Provides configuration for both local development and Cloud Run deployment,
    with sensible defaults for local development.

    Inherits session configuration from SessionConfig.

    Attributes:
        agent_name: Unique agent identifier for resources and logs.
        log_level: Logging verbosity level.
        serve_web_interface: Whether to serve the ADK web interface.
        reload_agents: Whether to reload agents on file changes (local dev only).
        openrouter_api_key: OpenRouter API key for LiteLLM integration.
        allow_origins: JSON array string of allowed CORS origins.
        host: Server host (127.0.0.1 for local, 0.0.0.0 for containers).
        port: Server port.
    """

    agent_name: str = Field(
        ...,
        alias="AGENT_NAME",
        description="Unique agent identifier for resources and logs",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
        description="Logging verbosity level",
    )

    serve_web_interface: bool = Field(
        default=False,
        alias="SERVE_WEB_INTERFACE",
        description="Whether to serve the ADK web interface",
    )

    reload_agents: bool = Field(
        default=False,
        alias="RELOAD_AGENTS",
        description="Whether to reload agents on file changes (local dev only)",
    )

    openrouter_api_key: str | None = Field(
        default=None,
        alias="OPENROUTER_API_KEY",
        description="OpenRouter API key for LiteLLM integration",
    )

    allow_origins: str = Field(
        default='["http://127.0.0.1", "http://127.0.0.1:8080"]',
        alias="ALLOW_ORIGINS",
        description="JSON array string of allowed CORS origins",
    )

    host: str = Field(
        default="127.0.0.1",
        alias="HOST",
        description="Server host (127.0.0.1 for local, 0.0.0.0 for containers)",
    )

    port: int = Field(
        default=8080,
        alias="PORT",
        description="Server port",
    )

    def print_config(self) -> None:
        """Print server configuration for user verification."""
        print("\n\n✅ Environment variables loaded for server:\n")
        print(f"AGENT_NAME:            {self.agent_name}")
        print(f"LOG_LEVEL:             {self.log_level}")
        print(f"SERVE_WEB_INTERFACE:   {self.serve_web_interface}")
        print(f"RELOAD_AGENTS:         {self.reload_agents}")
        print(f"AGENT_ENGINE:          {self.agent_engine}")
        print(f"DATABASE_URL:          {self.database_url}")
        if self.database_url:
            print(f"DB_POOL_PRE_PING:      {self.db_pool_pre_ping}")
            print(f"DB_POOL_RECYCLE:       {self.db_pool_recycle}")
            print(f"DB_POOL_SIZE:          {self.db_pool_size}")
            print(f"DB_MAX_OVERFLOW:       {self.db_max_overflow}")
            print(f"DB_POOL_TIMEOUT:       {self.db_pool_timeout}")
        masked_key = "********" if self.openrouter_api_key else None
        print(f"OPENROUTER_KEY:        {masked_key}")
        print(f"HOST:                  {self.host}")
        print(f"PORT:                  {self.port}")
        print(f"ALLOW_ORIGINS:         {self.allow_origins}\n\n")

    @property
    def allow_origins_list(self) -> list[str]:
        """Parse allow_origins JSON string to list.

        Returns:
            List of allowed origin strings.

        Raises:
            ValueError: If JSON parsing fails or result is not a list of strings.
        """
        try:
            origins = json.loads(self.allow_origins)
            if not isinstance(origins, list) or not all(
                isinstance(o, str) for o in origins
            ):
                msg = "ALLOW_ORIGINS must be a JSON array of strings"
                raise ValueError(msg)
            return origins
        except json.JSONDecodeError as e:
            msg = f"Failed to parse ALLOW_ORIGINS as JSON: {e}"
            raise ValueError(msg) from e
