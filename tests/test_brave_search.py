"""Tests for the Brave web search tool."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from conftest import MockState, MockToolContext

from agent.tools import brave_web_search


class TestBraveWebSearch:
    """Tests for the Brave web search tool."""

    def test_missing_api_key_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        tool_context = MockToolContext(state=MockState({}))

        result = brave_web_search(tool_context, query="python testing")  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "BRAVE_SEARCH_API_KEY" in result["message"]

    def test_blank_query_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        result = brave_web_search(tool_context, query="   ")  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "non-empty" in result["message"]

    def test_invalid_count_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        result = brave_web_search(tool_context, query="python", count=21)  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "between 1 and 20" in result["message"]

    def test_successful_search_returns_normalized_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        response = MagicMock()
        response.json.return_value = {
            "query": {
                "original": "python testing",
                "more_results_available": True,
            },
            "web": {
                "results": [
                    {
                        "title": "Pytest docs",
                        "url": "https://docs.pytest.org/",
                        "description": "Testing framework",
                        "extra_snippets": ["Fixtures", "Parametrize"],
                        "age": "2 days ago",
                        "language": "en",
                    }
                ]
            },
        }
        response.raise_for_status.return_value = None

        with patch("agent.tools.httpx.get", return_value=response) as mock_get:
            result = brave_web_search(
                tool_context,  # type: ignore[arg-type]
                query="python testing",
                count=3,
                offset=1,
                country="us",
                search_lang="en",
                extra_snippets=True,
            )

        assert result["status"] == "success"
        assert result["query"] == "python testing"
        assert result["count"] == 1
        assert result["more_results_available"] is True
        assert result["results"][0]["title"] == "Pytest docs"
        assert result["results"][0]["extra_snippets"] == ["Fixtures", "Parametrize"]

        mock_get.assert_called_once_with(
            "https://api.search.brave.com/res/v1/web/search",
            params={
                "q": "python testing",
                "count": 3,
                "offset": 1,
                "safesearch": "moderate",
                "extra_snippets": True,
                "country": "US",
                "search_lang": "en",
            },
            headers={"X-Subscription-Token": "test-key"},
            timeout=15.0,
        )

    def test_invalid_offset_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        result = brave_web_search(tool_context, query="python", offset=10)  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "offset" in result["message"]

    def test_invalid_safesearch_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        result = brave_web_search(tool_context, query="python", safesearch="bogus")  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "safesearch" in result["message"]

    def test_http_transport_error_returns_clean_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        with patch(
            "agent.tools.httpx.get",
            side_effect=httpx.TimeoutException("timed out"),
        ):
            result = brave_web_search(tool_context, query="python")  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "Brave search request failed" in result["message"]

    def test_http_status_error_returns_clean_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
        tool_context = MockToolContext(state=MockState({}))

        request = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
        response = httpx.Response(status_code=429, request=request)
        error = httpx.HTTPStatusError(
            "rate limited", request=request, response=response
        )

        with patch("agent.tools.httpx.get", side_effect=error):
            result = brave_web_search(tool_context, query="python")  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "HTTP 429" in result["message"]
