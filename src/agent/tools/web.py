from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from agent.core.actions import ErrorCode, InternalAction, Observation, make_error_observation, make_observation


DEFAULT_MAX_RESULTS = 5
MAX_RESULTS = 8
SEARCH_URL = "https://duckduckgo.com/html/?q={query}"


def execute_web_search(action: InternalAction, *, observation_index: int) -> Observation:
    query = str(action.action.args["query"]).strip()
    max_results = _max_results(action.action.args.get("max_results"))
    try:
        results = search_web(query, max_results)
    except OSError as exc:
        return make_error_observation(
            action.action_id,
            action.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message=f"Web search failed: {exc}",
            details={"query": query},
        )
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Web search returned {len(results)} result(s).",
        data={"query": query, "results": results},
    )


def search_web(query: str, max_results: int) -> list[dict[str, str]]:
    request = Request(
        SEARCH_URL.format(query=quote_plus(query)),
        headers={"User-Agent": "AgentWorkbench/0.1"},
    )
    with urlopen(request, timeout=12) as response:  # nosec B310 - user-controlled feature flag gates this tool.
        html = response.read().decode("utf-8", errors="replace")
    parser = _DuckDuckGoParser(max_results)
    parser.feed(html)
    parser.close()
    return parser.results


def _max_results(value: int | None) -> int:
    return min(max(int(value or DEFAULT_MAX_RESULTS), 1), MAX_RESULTS)


class _DuckDuckGoParser(HTMLParser):
    def __init__(self, max_results: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_results = max_results
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._finish_current()
            self._current = {"title": "", "url": _clean_url(attr.get("href", "")), "snippet": ""}
            self._capture = "title"
        elif self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"

    def handle_data(self, data: str) -> None:
        if self._current is None or self._capture is None:
            return
        self._current[self._capture] = (self._current[self._capture] + " " + data.strip()).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "div"}:
            self._capture = None

    def close(self) -> None:
        self._finish_current()
        super().close()

    def _finish_current(self) -> None:
        if self._current and self._current["title"] and len(self.results) < self.max_results:
            self.results.append(dict(self._current))
        self._current = None
        self._capture = None


def _clean_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.path == "/l/":
        value = parse_qs(parsed.query).get("uddg", [""])[0]
        if value:
            return unquote(value)
    return raw
