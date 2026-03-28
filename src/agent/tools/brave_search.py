"""Brave web search tool for the ADK agent."""

import logging
import os
from typing import Any

import httpx
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

_BRAVE_SEARCH_API_URL = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_SEARCH_TIMEOUT_SECONDS = 15.0
_BRAVE_SEARCH_DEFAULT_COUNT = 5
_BRAVE_SEARCH_MAX_COUNT = 20
_BRAVE_SEARCH_MAX_OFFSET = 9
_BRAVE_SEARCH_ALLOWED_SAFESEARCH = {"off", "moderate", "strict"}


def brave_web_search(
    tool_context: ToolContext,  # noqa: ARG001
    query: str,
    count: int = _BRAVE_SEARCH_DEFAULT_COUNT,
    offset: int = 0,
    safesearch: str = "moderate",
    country: str | None = None,
    search_lang: str | None = None,
    extra_snippets: bool = False,
) -> dict[str, Any]:
    """Search the public web with Brave Search.

    Uses the Brave Web Search API. Requires ``BRAVE_SEARCH_API_KEY`` in the
    environment. Returns compact, agent-friendly result objects with title, URL,
    description, and optional extra snippets.

    Args:
        tool_context: ADK ToolContext (unused; required by ADK).
        query: Search query string.
        count: Number of results to return (1-20, default 5).
        offset: Pagination offset (0-9, default 0).
        safesearch: Adult-content filtering: off, moderate, or strict.
        country: Optional two-letter country code like ``US`` or ``IN``.
        search_lang: Optional language code like ``en`` or ``de``.
        extra_snippets: Whether Brave should include additional snippets.

    Returns:
        Status, normalized search results, and pagination metadata.
    """
    _ = tool_context

    trimmed_query = query.strip()
    if not trimmed_query:
        return {"status": "error", "message": "query must be a non-empty string."}

    if count < 1 or count > _BRAVE_SEARCH_MAX_COUNT:
        return {
            "status": "error",
            "message": (
                f"count must be between 1 and {_BRAVE_SEARCH_MAX_COUNT} results."
            ),
        }

    if offset < 0 or offset > _BRAVE_SEARCH_MAX_OFFSET:
        return {
            "status": "error",
            "message": (f"offset must be between 0 and {_BRAVE_SEARCH_MAX_OFFSET}."),
        }

    normalized_safesearch = safesearch.strip().lower()
    if normalized_safesearch not in _BRAVE_SEARCH_ALLOWED_SAFESEARCH:
        allowed_values = ", ".join(sorted(_BRAVE_SEARCH_ALLOWED_SAFESEARCH))
        return {
            "status": "error",
            "message": f"safesearch must be one of: {allowed_values}.",
        }

    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "error",
            "message": "BRAVE_SEARCH_API_KEY is not configured.",
        }

    params: dict[str, str | int | bool] = {
        "q": trimmed_query,
        "count": count,
        "offset": offset,
        "safesearch": normalized_safesearch,
        "extra_snippets": extra_snippets,
    }
    if country:
        params["country"] = country.strip().upper()
    if search_lang:
        params["search_lang"] = search_lang.strip().lower()

    headers = {"X-Subscription-Token": api_key}

    try:
        response = httpx.get(
            _BRAVE_SEARCH_API_URL,
            params=params,
            headers=headers,
            timeout=_BRAVE_SEARCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        logger.warning(
            "Brave search failed with HTTP %s for query=%r",
            error.response.status_code,
            trimmed_query,
        )
        return {
            "status": "error",
            "message": (
                f"Brave search request failed with HTTP {error.response.status_code}."
            ),
        }
    except httpx.HTTPError as error:
        logger.warning(
            "Brave search request error for query=%r: %s", trimmed_query, error
        )
        return {
            "status": "error",
            "message": f"Brave search request failed: {error}",
        }

    payload = response.json()
    query_payload = payload.get("query", {})
    web_payload = payload.get("web", {})
    raw_results = web_payload.get("results", [])

    normalized_results: list[dict[str, Any]] = []
    for item in raw_results:
        normalized_results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "extra_snippets": item.get("extra_snippets", []),
                "age": item.get("age"),
                "language": item.get("language"),
            }
        )

    logger.info(
        "Brave web search returned %s results for query=%r",
        len(normalized_results),
        trimmed_query,
    )

    return {
        "status": "success",
        "query": query_payload.get("original", trimmed_query),
        "results": normalized_results,
        "count": len(normalized_results),
        "more_results_available": bool(
            query_payload.get("more_results_available", False)
        ),
        "message": f"Found {len(normalized_results)} web result(s).",
    }


__all__ = ["brave_web_search"]
