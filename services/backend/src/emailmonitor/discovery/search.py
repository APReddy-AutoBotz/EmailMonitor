"""Inert, resource-bounded connector parser for authored synthetic search HTML.

Production transport must run this parser in the network-none worker boundary.
No script, stylesheet, browser action, file or network access exists here.
"""

import hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.config import Settings
from emailmonitor.discovery.planning import ARTICLE_PATHS, SEARCH_PATHS
from emailmonitor.fetching.fixture import HOSTS, require_fixture
from emailmonitor.fetching.safety import FetchDenied, classify_url


class SearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    url: str = Field(max_length=2048)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    articles: list[str] = Field(max_length=500)
    next_url: str | None = Field(default=None, max_length=2048)
    reported_total: int | None = Field(default=None, ge=0, le=1000000)
    exhausted: bool
    selector_valid: bool


class _Search(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = url
        self.stack: list[str] = []
        self.results_depth: int | None = None
        self.results_seen = False
        self.result_rows = 0
        self.articles: list[str] = []
        self.next_url: str | None = None
        self.reported_total: int | None = None
        self.exhausted = False
        self.tags = 0
        self.valid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags += 1
        if self.tags > 2048 or len(self.stack) > 64 or len(attrs) > 35:
            raise FetchDenied("search_parse_limit")
        if len({key for key, _ in attrs}) != len(attrs):
            raise FetchDenied("search_attribute_ambiguity")
        a = dict(attrs)
        hidden = any(t in ("script", "style", "template") for t in self.stack)
        if not hidden:
            if tag == "ol" and a.get("class") == "search-results":
                if self.results_seen:
                    self.valid = False
                self.results_seen = True
                self.results_depth = len(self.stack)
            if "data-reported-total" in a:
                raw = a["data-reported-total"] or ""
                if not raw.isascii() or not raw.isdecimal() or len(raw) > 7:
                    self.valid = False
                else:
                    total = int(raw)
                    if total > 1000000 or self.reported_total is not None:
                        self.valid = False
                    else:
                        self.reported_total = total
            if a.get("data-pagination-exhausted") == "true":
                self.exhausted = True
            if tag == "li" and self.results_depth is not None:
                self.result_rows += 1
            if tag == "a" and a.get("class") == "article-link" and self.results_depth is not None:
                self.articles.append(self.link(a.get("href"), ARTICLE_PATHS))
                if len(self.articles) > 500:
                    raise FetchDenied("search_parse_limit")
            if tag == "a" and a.get("rel") == "next":
                if self.next_url is not None:
                    self.valid = False
                self.next_url = self.link(a.get("href"), SEARCH_PATHS)
        if tag not in {"meta", "link", "img", "br", "hr", "input", "source", "wbr"}:
            self.stack.append(tag)

    def link(self, href: str | None, paths: frozenset[str]) -> str:
        if not href or len(href) > 2048:
            raise FetchDenied("search_link_denied")
        url = classify_url(urljoin(self.url, href), HOSTS)
        if url.path not in paths:
            raise FetchDenied("search_link_denied")
        return url.normalized

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            self.valid = False
            return
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        if index != len(self.stack) - 1:
            self.valid = False
        del self.stack[index:]
        if self.results_depth is not None and len(self.stack) <= self.results_depth:
            self.results_depth = None


def parse_search(settings: Settings, url: str, payload: bytes) -> SearchPage:
    require_fixture(settings)
    safe = classify_url(url, HOSTS)
    if safe.path not in SEARCH_PATHS or type(payload) is not bytes or len(payload) > 32768:
        raise FetchDenied("search_parse_limit")
    try:
        html = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise FetchDenied("search_encoding_denied") from None
    parser = _Search(safe.normalized)
    parser.feed(html)
    parser.close()
    return SearchPage(
        url=safe.normalized,
        digest=hashlib.sha256(payload).hexdigest(),
        articles=parser.articles,
        next_url=parser.next_url,
        reported_total=parser.reported_total,
        exhausted=parser.exhausted,
        selector_valid=parser.valid
        and parser.result_rows == len(parser.articles)
        and parser.results_seen
        and not parser.stack
        and not (parser.exhausted and parser.next_url is not None)
        and (parser.exhausted or parser.next_url is not None),
    )
