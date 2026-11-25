from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..registry import ToolSpec


_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)


# DuckDuckGo answers a plainly labelled script with an anti-bot page and no results, so the request carries a full browser header set.
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}
_ENDPOINT = "https://html.duckduckgo.com/html/?"


def _real_url(href: str) -> str:
    """The page a result points at: DuckDuckGo wraps links as //duckduckgo.com/l/?uddg=<the real url>."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def _antibot_page(raw: str, query: str) -> bool:
    """DuckDuckGo's anti-bot page: it says "anomaly". The results page echoes the query back (as typed, HTML-escaped and
    URL-encoded), so those echoes are removed first: an empty search for "anomaly detection" must not read as a block."""
    page = raw.lower()
    for echo in {query, html.escape(query), urllib.parse.quote_plus(query), urllib.parse.quote(query)}:
        page = page.replace(echo.lower(), " ")
    return "anomaly" in page


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


class WebSearchTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="WebSearch",
            reaches_network=True,
            description="Search the web and return top results.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "num": {"type": "integer"},
                },
                "required": ["query"],
            },
            is_read_only=True,
            max_result_size_chars=50_000,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        """Ask before every search, showing the whole query: it goes to DuckDuckGo, and whatever the model wrote rides in it (WebFetch
        asks for the same reason). A `WebSearch` allow rule, which "don't ask again" saves, skips the question."""
        query = tool_input.get("query")
        if not isinstance(query, str) or not query.strip():
            return PermissionResult.allow()  # Input validation happens in run()
        shown = query if len(query) <= 300 else f"{query[:300]}… (+{len(query) - 300} more characters)"
        return PermissionResult.ask(message=f"Search the web (DuckDuckGo) for: {shown}")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        query = tool_input["query"]
        if not isinstance(query, str) or not query.strip():
            raise ToolInputError("query must be a non-empty string")
        num = tool_input.get("num", 5)
        if not isinstance(num, int) or num < 1 or num > 10:
            raise ToolInputError("num must be an integer between 1 and 10")

        results: list[dict[str, str]] = []
        failure: str | None = None        # why the last attempt got nothing: "anti-bot" or the HTTP status of a rate limit
        for attempt in range(2):          # one retry, only after a rate limit or the anti-bot page
            failure = None                # each attempt starts clean
            url = _ENDPOINT + urllib.parse.urlencode({"q": query})
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=_BROWSER_HEADERS), timeout=15) as resp:
                    raw = resp.read(1_000_000).decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                e.close()
                if e.code not in {429, 503}:
                    raise ToolExecutionError(f"web search failed: HTTP {e.code} from the search engine") from e
                failure = f"HTTP {e.code}"
            else:
                results = self._parse(raw, num)
                if results:
                    break
                if not _antibot_page(raw, query):
                    break                 # a genuine empty answer: no retry
                failure = "anti-bot"
            if attempt == 0:
                time.sleep(2)
        if not results and failure == "anti-bot":
            raise ToolExecutionError("web search was blocked by the search engine (anti-bot check); try again later or use WebFetch on a known page")
        if not results and failure:   # rate limited or unavailable twice: say that, not "anti-bot"
            raise ToolExecutionError(f"web search failed: {failure} from the search engine twice; try again later")
        return ToolResult(name="WebSearch", output={"query": query, "results": results})

    @staticmethod
    def _parse(raw: str, num: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for match in _RESULT_RE.finditer(raw):
            results.append(
                {
                    "title": _strip_tags(match.group("title")),
                    "url": _real_url(match.group("url")),
                    "snippet": _strip_tags(match.group("snippet")),
                }
            )
            if len(results) >= num:
                break
        return results
