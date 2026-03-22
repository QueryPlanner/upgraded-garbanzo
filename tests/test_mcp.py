"""Tests for MCP toolset configuration helpers."""

from unittest.mock import AsyncMock, patch

import pytest
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from agent.mcp import (
    DEFAULT_NOTION_MCP_ARGS,
    DEFAULT_NOTION_MCP_COMMAND,
    DEFAULT_NOTION_MCP_TIMEOUT_SECONDS,
    ResilientMcpToolset,
    create_mcp_toolsets,
)


class TestCreateMcpToolsets:
    """Tests for optional MCP toolset creation."""

    def test_returns_empty_list_when_notion_is_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOTION_MCP_ENABLED", raising=False)

        toolsets = create_mcp_toolsets()

        assert toolsets == []

    def test_skips_notion_toolset_without_token_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.delenv("NOTION_TOKEN", raising=False)

        toolsets = create_mcp_toolsets()

        assert toolsets == []

    def test_creates_notion_toolset_with_stdio_server_when_token_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.setenv("NOTION_TOKEN", "notion-token")

        toolsets = create_mcp_toolsets()

        assert len(toolsets) == 1
        assert isinstance(toolsets[0], McpToolset)
        assert isinstance(toolsets[0]._connection_params, StdioConnectionParams)
        assert (
            toolsets[0]._connection_params.timeout == DEFAULT_NOTION_MCP_TIMEOUT_SECONDS
        )
        server_params = toolsets[0]._connection_params.server_params
        assert isinstance(server_params, StdioServerParameters)
        assert server_params.command == DEFAULT_NOTION_MCP_COMMAND
        assert server_params.args == DEFAULT_NOTION_MCP_ARGS
        assert server_params.env is not None
        assert "NOTION_TOKEN" in server_params.env
        assert toolsets[0].get_auth_config() is None

    def test_uses_custom_timeout_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.setenv("NOTION_TOKEN", "notion-token")
        monkeypatch.setenv("NOTION_MCP_TIMEOUT_SECONDS", "45")

        toolsets = create_mcp_toolsets()

        assert len(toolsets) == 1
        assert isinstance(toolsets[0]._connection_params, StdioConnectionParams)
        assert toolsets[0]._connection_params.timeout == 45.0

    def test_skips_notion_when_command_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.setenv("NOTION_TOKEN", "notion-token")
        monkeypatch.setenv("NOTION_MCP_COMMAND", "   ")

        toolsets = create_mcp_toolsets()

        assert toolsets == []

    def test_invalid_timeout_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.setenv("NOTION_TOKEN", "notion-token")
        monkeypatch.setenv("NOTION_MCP_TIMEOUT_SECONDS", "not-a-number")

        toolsets = create_mcp_toolsets()

        assert len(toolsets) == 1
        assert (
            toolsets[0]._connection_params.timeout == DEFAULT_NOTION_MCP_TIMEOUT_SECONDS
        )

    def test_non_positive_timeout_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.setenv("NOTION_TOKEN", "notion-token")
        monkeypatch.setenv("NOTION_MCP_TIMEOUT_SECONDS", "0")

        toolsets = create_mcp_toolsets()

        assert len(toolsets) == 1
        assert (
            toolsets[0]._connection_params.timeout == DEFAULT_NOTION_MCP_TIMEOUT_SECONDS
        )

    @pytest.mark.asyncio
    async def test_resilient_toolset_returns_empty_list_on_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
        monkeypatch.setenv("NOTION_TOKEN", "notion-token")

        toolset = create_mcp_toolsets()[0]
        assert isinstance(toolset, ResilientMcpToolset)

        with patch.object(
            McpToolset,
            "get_tools",
            new=AsyncMock(side_effect=ConnectionError("401 Unauthorized")),
        ):
            tools = await toolset.get_tools()

        assert tools == []
