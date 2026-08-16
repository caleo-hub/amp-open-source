from __future__ import annotations

from typing import Any

import httpx

from ..config.settings import (
    SEARXNG_BASE_URL,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_MAX_SNIPPET_CHARS,
    WEB_SEARCH_TIMEOUT_SECONDS,
    RUNTIME_TOOL_TIMEOUT_SECONDS,
)


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def search_web(query: str) -> dict:
    query = query.strip()

    if not query:
        return {
            "ok": False,
            "error": "empty_query",
            "results": [],
        }

    try:
        response = httpx.get(
            f"{SEARXNG_BASE_URL.rstrip('/')}/search",
            params={
                "q": query,
                "format": "json",
            },
            timeout=min(WEB_SEARCH_TIMEOUT_SECONDS, RUNTIME_TOOL_TIMEOUT_SECONDS),
        )

        response.raise_for_status()
        payload = response.json()

    except httpx.TimeoutException:
        return {
            "ok": False,
            "error": "timeout",
            "results": [],
        }

    except httpx.HTTPError:
        return {
            "ok": False,
            "error": "service_unavailable",
            "results": [],
        }

    except ValueError:
        return {
            "ok": False,
            "error": "invalid_response",
            "results": [],
        }

    results = []

    for item in payload.get("results", []):
        url = _clean_text(item.get("url"), 2000)

        if not url:
            continue

        results.append(
            {
                "title": _clean_text(item.get("title"), 300),
                "url": url,
                "snippet": _clean_text(
                    item.get("content"),
                    WEB_SEARCH_MAX_SNIPPET_CHARS,
                ),
            }
        )

        if len(results) >= WEB_SEARCH_MAX_RESULTS:
            break

    return {
        "ok": True,
        "query": query,
        "results": results,
    }