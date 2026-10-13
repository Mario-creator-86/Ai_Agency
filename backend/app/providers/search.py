"""A web search API behind the allowlist: it may name pages, and nothing else.

Measured before this adapter existed: the studio found pages only through the search address
the Owner typed per host, and only en/ro Wikipedia carried one; the Researcher guessed the
rest and most guesses returned 404; the latest live run fetched 0 pages.

A search engine is a different kind of vendor from the media providers. It does not make
anything the studio keeps: what comes back is a list of addresses, and every address is then
judged by the same allowlist and read by the same DNS-pinned retriever as a page the Owner
pasted by hand. Three rules follow, and the tests hold the adapter to them:

- **Addresses only.** Most engines return a cached copy, a snippet or an "answer" next to each
  result. The adapter never reads those fields: a page's text is what the studio's own
  retriever downloads, or the page is not a source. Reading the engine's copy would be
  fetching through a third party what the studio would not fetch itself.
- **The allowlist is applied by the caller, not widened by the engine.** The adapter returns
  every address the engine named; ``app.research.service.find_pages`` keeps the ones on
  authorised hosts and counts the rest as dropped. Nothing here knows the allowlist, so
  nothing here can be talked into extending it.
- **One documented HTTPS JSON contract, configured by the Owner.** The endpoint, the header
  that carries the key, the path to the result list and the field names are configuration
  (``app.integrations.catalog``, kind ``search``); the key lives in the vault. The adapter
  builds one GET, sends one header with the key, and reads one list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from app.providers.media_http import MediaProviderError, request

#: What a probe asks for. One neutral word: the answer's shape is what is checked, not its
#: content, and a probe must not look like a research query in the vendor's logs.
PROBE_QUERY = "encyclopedia"
#: More results than this from one query are noise for a studio that reads four pages a
#: topic; the cap also bounds what a hostile answer can make the caller iterate.
MAX_RESULTS = 50
MAX_URL_CHARS = 1000


class SearchProviderError(MediaProviderError):
    """The engine did not answer the contract; the caller finds no pages this way today."""


@dataclass(frozen=True)
class SearchResult:
    """An address the engine named, with its title. Never the engine's copy of the page."""

    url: str
    title: str


def results_at(payload: Any, path: str) -> list[Any] | None:
    """The list at a dotted path inside the engine's JSON, or None when it is not there."""
    current = payload
    for key in [part for part in path.split(".") if part]:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, list) else None


class SearchProvider:
    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict[str, str], api_key: str) -> None:
        endpoint = urlsplit(str(config.get("endpoint", "")))
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise SearchProviderError("The search endpoint must be an https address")
        self.host = endpoint.hostname
        self.path = endpoint.path or "/"
        self.query_param = (config.get("query_param") or "q").strip() or "q"
        self.auth_header = (config.get("auth_header") or "Authorization").strip()
        self.results_path = (config.get("results_path") or "results").strip()
        self.url_field = (config.get("url_field") or "url").strip() or "url"
        self.title_field = (config.get("title_field") or "title").strip() or "title"
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        # "Authorization" carries a bearer token by convention; any other header carries the
        # key as it is (Brave's X-Subscription-Token, for one). The key is never logged.
        value = self._api_key
        if self.auth_header.lower() == "authorization" and not value.lower().startswith("bearer "):
            value = "Bearer " + value
        return {self.auth_header: value, "Accept": "application/json"}

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Ask the engine for these words; addresses and titles, at most ``limit``."""
        words = " ".join(str(query).split())[:200]
        if not words:
            return []
        path = f"{self.path}?{self.query_param}={quote(words, safe='')}"
        try:
            payload, _, _ = request(self.host, "GET", path, self._headers(), timeout=20)
        except MediaProviderError as exc:
            raise SearchProviderError(str(exc)) from exc
        items = results_at(payload, self.results_path)
        if items is None:
            raise SearchProviderError(
                f"{self.host} did not answer a result list at the configured path"
            )
        found: list[SearchResult] = []
        for item in items[:MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            url = item.get(self.url_field)
            if not isinstance(url, str) or not 10 <= len(url) <= MAX_URL_CHARS:
                continue
            title = item.get(self.title_field)
            found.append(SearchResult(url.strip(), " ".join(str(title or "").split())[:200]))
            if len(found) >= max(1, limit):
                break
        return found

    def probe(self) -> bool:
        """Whether the key is accepted and the answer has the configured shape.

        Called by the Owner's "Verify access": one query, one word, nothing stored. A failed
        request or a missing result list is False, never an exception the interface would
        have to interpret.
        """
        try:
            self.search(PROBE_QUERY, limit=1)
        except SearchProviderError:
            return False
        return True
