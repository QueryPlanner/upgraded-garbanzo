"""Helpers for optional MCP toolsets used by the agent."""

import logging
import os
from typing import cast

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import McpToolset
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

logger = logging.getLogger(__name__)

DEFAULT_NOTION_MCP_COMMAND = "npx"
DEFAULT_NOTION_MCP_ARGS = ["-y", "@notionhq/notion-mcp-server"]
DEFAULT_NOTION_MCP_TIMEOUT_SECONDS = 30.0


class ResilientMcpToolset(McpToolset):
    """MCP toolset that degrades gracefully when the server fails."""

    async def get_tools(
        self, readonly_context: ReadonlyContext | None = None
    ) -> list[BaseTool]:
        try:
            return cast(list[BaseTool], await super().get_tools(readonly_context))
        except Exception as error:
            logger.warning("Skipping MCP toolset after connection failure: %s", error)
            return []


def _env_flag(name: str) -> bool:
    """Return True when an environment flag is explicitly enabled."""
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def create_mcp_toolsets() -> list[McpToolset]:
    """Create optional MCP toolsets enabled through environment variables."""
    toolsets: list[McpToolset] = []

    notion_toolset = _create_notion_mcp_toolset()
    if notion_toolset is not None:
        toolsets.append(notion_toolset)

    return toolsets


def _create_notion_mcp_toolset() -> McpToolset | None:
    """Create the Notion MCP toolset when explicitly enabled."""
    if not _env_flag("NOTION_MCP_ENABLED"):
        return None

    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    if not notion_token:
        logger.warning("Skipping Notion MCP toolset because NOTION_TOKEN is missing.")
        return None

    notion_command = os.getenv("NOTION_MCP_COMMAND", DEFAULT_NOTION_MCP_COMMAND).strip()
    if not notion_command:
        logger.warning(
            "Skipping Notion MCP toolset because NOTION_MCP_COMMAND is empty."
        )
        return None

    server_env = os.environ.copy()
    server_env["NOTION_TOKEN"] = notion_token
    timeout_seconds = _read_notion_mcp_timeout_seconds()

    logger.info("Creating Notion MCP toolset using stdio server.")
    return ResilientMcpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=notion_command,
                args=list(DEFAULT_NOTION_MCP_ARGS),
                env=server_env,
            ),
            timeout=timeout_seconds,
        ),
        tool_name_prefix="notion",
        # The current Notion MCP server exposes tools but does not implement
        # the optional MCP resources/list methods. Keep tool access enabled
        # without the noisy resource-probing warnings.
        use_mcp_resources=False,
    )


def _read_notion_mcp_timeout_seconds() -> float:
    """Read the MCP stdio timeout with a safe default."""
    raw_value = os.getenv("NOTION_MCP_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_NOTION_MCP_TIMEOUT_SECONDS

    try:
        parsed_value = float(raw_value)
    except ValueError:
        logger.warning(
            "Invalid NOTION_MCP_TIMEOUT_SECONDS=%r. Using default %s.",
            raw_value,
            DEFAULT_NOTION_MCP_TIMEOUT_SECONDS,
        )
        return DEFAULT_NOTION_MCP_TIMEOUT_SECONDS

    if parsed_value <= 0:
        logger.warning(
            "NOTION_MCP_TIMEOUT_SECONDS must be positive. Using default %s.",
            DEFAULT_NOTION_MCP_TIMEOUT_SECONDS,
        )
        return DEFAULT_NOTION_MCP_TIMEOUT_SECONDS

    return parsed_value
