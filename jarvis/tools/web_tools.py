"""Web tools — search and page fetch (used when local knowledge is not enough)."""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any, Dict, List
from urllib.parse import quote_plus, urlparse

import httpx

from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
MARKUP_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")
NL_RE = re.compile(r"\n{3,}")


def _strip_html(raw: str) -> str:
    text = TAG_RE.sub(" ", raw)
    text = MARKUP_RE.sub(" ", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    text = NL_RE.sub("\n\n", text)
    return text.strip()


async def _duckduckgo(query: str, limit: int) -> List[Dict[str, str]]:
    url = "https://html.duckduckgo.com/html/"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.post(url, data={"q": query}, headers={"User-Agent": UA})
        r.raise_for_status()
        body = r.text
    results: List[Dict[str, str]] = []
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'(?:class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?',
        body,
        re.S,
    )
    for m in blocks[:limit]:
        title = html.unescape(re.sub(r"<[^>]+>", "", m[1])).strip()
        snippet = html.unescape(re.sub(r"<[^>]+>", "", m[3] or "")).strip()
        href = html.unescape(m[2])
        if href.startswith("//duckduckgo.com/l/?uddg="):
            from urllib.parse import unquote, parse_qs

            qs = parse_qs(urlparse("https:" + href).query)
            href = unquote((qs.get("uddg") or [href])[0])
        if title:
            results.append({"title": title, "url": href, "snippet": snippet})
    return results


async def _brave(query: str, limit: int, api_key: str) -> List[Dict[str, str]]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        }
        for item in (data.get("web", {}).get("results") or [])[:limit]
    ]


async def _searxng(query: str, limit: int, base_url: str) -> List[Dict[str, str]]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{base_url.rstrip('/')}/search",
            params={"q": query, "format": "json"},
            headers={"User-Agent": UA},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("content", "")}
        for i in (data.get("results") or [])[:limit]
    ]


async def _web_search(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or ctx.cfg.tools.search_results)
    provider = (ctx.cfg.tools.web_provider or "duckduckgo").lower()

    try:
        if provider == "brave":
            key = os.environ.get(ctx.cfg.tools.brave_api_key_env, "")
            if not key:
                return {"ok": False, "output": "BRAVE_API_KEY is not set — switch tools.web_provider to duckduckgo"}
            results = await _brave(query, limit, key)
        elif provider == "searxng":
            results = await _searxng(query, limit, ctx.cfg.tools.searxng_url)
        else:
            results = await _duckduckgo(query, limit)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "query": query, "output": f"search failed: {exc}", "error": str(exc)}

    if not results:
        return {"ok": True, "query": query, "results": [], "output": f"no results for '{query}'"}
    lines = [f"{i+1}. {r['title']} — {r['url']}" + (f"\n   {r['snippet']}" if r.get("snippet") else "") for i, r in enumerate(results)]
    return {"ok": True, "query": query, "results": results, "output": "\n".join(lines)}


async def _fetch_url(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    url = str(args.get("url") or "").strip()
    max_chars = int(args.get("max_chars") or ctx.cfg.tools.fetch_max_chars)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": UA})
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            raw = r.text
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "output": f"fetch failed: {exc}", "error": str(exc)}

    if "json" in content_type:
        try:
            text = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)[:max_chars]
        except ValueError:
            text = raw[:max_chars]
    else:
        text = _strip_html(raw)[:max_chars]
    return {"ok": True, "url": url, "chars": len(text), "output": text}


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="web_search",
            description="Search the web for current information. Use only for recent or external facts.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {"type": "integer", "description": "Number of results (default 5)."},
                },
                "required": ["query"],
            },
            risk=RiskLevel.SAFE,
            category="web",
            handler=_web_search,
        ),
        ToolSpec(
            name="fetch_url",
            description="Download a web page and return its readable text.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Absolute URL."},
                    "max_chars": {"type": "integer", "description": "Truncate after N characters."},
                },
                "required": ["url"],
            },
            risk=RiskLevel.SAFE,
            category="web",
            handler=_fetch_url,
        ),
    ]
