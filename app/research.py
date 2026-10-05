"""Web research for the agent: search the web and read pages, safely."""
import logging

import httpx

from app.config import get_settings
from app.integrations.google import html_to_text
from app.sentinel import check_url

log = logging.getLogger(__name__)
MAX_BYTES = 2_000_000
UA = "Mozilla/5.0 (compatible; AideAssistant/1.0; +https://github.com/nomaansyed717-sy/personal-assistant)"

_http: httpx.Client | None = None


def http() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": UA})
    return _http


def set_http(client: httpx.Client | None) -> None:
    global _http
    _http = client


class ResearchError(Exception):
    pass


def search(query: str, max_results: int = 6) -> list[dict]:
    s = get_settings()
    if s.tavily_api_key:
        r = http().post("https://api.tavily.com/search",
                        json={"api_key": s.tavily_api_key, "query": query, "max_results": max_results})
        r.raise_for_status()
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:300]}
                for x in r.json().get("results", [])]
    if s.brave_api_key:
        r = http().get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": max_results},
                       headers={"X-Subscription-Token": s.brave_api_key, "Accept": "application/json"})
        r.raise_for_status()
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("description") or "")[:300]}
                for x in r.json().get("web", {}).get("results", [])]
    raise ResearchError("web search isn't configured (set TAVILY_API_KEY or BRAVE_API_KEY)")


def read(url: str, max_chars: int = 12000) -> dict:
    """Fetch a page and return its readable text. Follows up to 5 redirects, re-checking each hop."""
    for _ in range(6):
        v = check_url(url)
        if not v.allowed:
            raise ResearchError(f"blocked by Sentinel: {v.reason}")
        with http().stream("GET", url) as r:
            if r.is_redirect and r.headers.get("location"):
                url = str(r.url.join(r.headers["location"]))
                continue
            if r.status_code >= 400:
                raise ResearchError(f"page returned {r.status_code}")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    break
            ctype = r.headers.get("content-type", "")
            text = body.decode(r.encoding or "utf-8", errors="replace")
            if "html" in ctype or text.lstrip().startswith("<"):
                title = ""
                lo = text.lower()
                if "<title" in lo:
                    start = lo.index("<title")
                    title = html_to_text(text[start: lo.find("</title>", start) + 8])[:200]
                text = html_to_text(text)
            else:
                title = ""
            return {"url": url, "title": title, "text": text[:max_chars]}
    raise ResearchError("too many redirects")
