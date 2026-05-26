"""Tool: web_search — perform web searches via SearXNG."""

from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx
import structlog

from app.core.config import get_settings
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool

logger = structlog.get_logger()


@register_tool
class WebSearchTool(BaseTool):
    """Perform web searches via a SearXNG instance."""

    name = "web_search"
    description = (
        "Search the web for information using a search engine. "
        "Returns a list of results with title, URL, and snippet. "
        "Use this to look up unknown senders, verify claims, or gather "
        "context about topics mentioned in emails."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 10).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Perform a web search."""
        query: str = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(content="Query parameter is required.", is_error=True)

        num_results: int = min(int(kwargs.get("num_results", 5)), 10)

        settings = get_settings()
        search_url = settings.search_provider_url

        if not search_url:
            return ToolResult(content="Web search is not configured. No search provider URL set.")

        logger.info("tool_web_search", query=query, num_results=num_results)

        try:
            async with httpx.AsyncClient(
                timeout=settings.tool_fetch_timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(
                    f"{search_url.rstrip('/')}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "categories": "general",
                    },
                    headers={"User-Agent": "mailassist-tool/1.0"},
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(content="Search request timed out.", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"Search failed: HTTP {e.response.status_code}",
                is_error=True,
            )
        except httpx.RequestError as e:
            return ToolResult(content=f"Search request failed: {e}", is_error=True)

        try:
            data = resp.json()
        except Exception:
            return ToolResult(content="Failed to parse search response.", is_error=True)

        results_raw = data.get("results", [])[:num_results]
        results = []
        for r in results_raw:
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:300],
                }
            )

        if not results:
            return ToolResult(content=f"No results found for '{query}'.")

        return ToolResult(content=json.dumps({"count": len(results), "results": results}, default=str))
