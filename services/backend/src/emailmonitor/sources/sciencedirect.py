"""Inert ScienceDirect V2 adapter primitives; no I/O, registration or authorization.

Request descriptions are plans, never permission to execute them. The existing live
source refusal remains unchanged. Callers must isolate parsing and bind results to
current tenant/source/job authority before persistence or any future fetch.
"""

import hashlib
import json
import math
import re
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from emailmonitor.fetching.safety import FetchDenied

API_ORIGIN: Literal["https://api.elsevier.com"] = "https://api.elsevier.com"
SEARCH_PATH = "/content/search/sciencedirect"
MAX_BYTES = 1_048_576
MAX_DEPTH = 16
MAX_NODES = 20_000


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Capabilities(Contract):
    source_id: Literal["elsevier_sciencedirect_v2"] = "elsevier_sciencedirect_v2"
    adapter_version: Literal["0.1.0"] = "0.1.0"
    live_execution: Literal[False] = False
    search_metadata: Literal[True] = True
    contact_extraction: Literal[False] = False
    website_search_url: Literal[False] = False


def _text(value: str) -> str:
    if not value.strip() or any(
        ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value
    ):
        raise ValueError("invalid_text")
    return value


class RequestPlan(Contract):
    method: Literal["PUT", "GET"]
    origin: Literal["https://api.elsevier.com"] = API_ORIGIN
    path: str
    media_type: Literal["application/json", "text/xml"]
    body: bytes = b""
    execution_enabled: Literal[False] = False


class SearchRequest(Contract):
    query: str = Field(min_length=1, max_length=250)
    offset: int = Field(default=0, ge=0, le=6000)
    show: Literal[10, 25, 50, 100] = 25
    sort_by: Literal["relevance", "date"] = "relevance"

    @field_validator("query")
    @classmethod
    def query_text(cls, value: str) -> str:
        return _text(value)

    def plan(self) -> RequestPlan:
        return RequestPlan(
            method="PUT", path=SEARCH_PATH, media_type="application/json", body=self.body()
        )

    def body(self) -> bytes:
        """Preserve spelling/Boolean case; never interpolate a URL or credentials."""
        return json.dumps(
            {
                "qs": self.query,
                "display": {
                    "offset": self.offset,
                    "show": self.show,
                    "sortBy": self.sort_by,
                },
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")


class ArticleIdentifier(Contract):
    kind: Literal["doi", "pii"]
    value: str = Field(min_length=1, max_length=256)

    @field_validator("value")
    @classmethod
    def identifier_text(cls, value: str) -> str:
        return _text(value)


def normalize_identifier(value: str) -> ArticleIdentifier:
    """Closed bare DOI/PII and HTTPS doi.org/ScienceDirect article URL subset.

    URLs are identifiers only, not destinations. No query, fragment, credentials,
    encoded paths, alternate host, search URL, PDF URL or arbitrary redirect.
    """
    if (
        type(value) is not str
        or not 1 <= len(value) <= 512
        or any(ord(c) <= 32 or ord(c) == 127 for c in value)
    ):
        raise FetchDenied("sciencedirect_identifier_denied")
    expected_kind = None
    if value.startswith("https://"):
        try:
            parts = urlsplit(value)
            if (
                parts.username is not None
                or parts.port is not None
                or parts.query
                or parts.fragment
                or "?" in value
                or "#" in value
            ):
                raise ValueError
            if parts.netloc == "doi.org":
                expected_kind = "doi"
                value = parts.path.removeprefix("/")
            elif parts.netloc == "www.sciencedirect.com" and parts.path.startswith(
                "/science/article/pii/"
            ):
                expected_kind = "pii"
                value = parts.path.removeprefix("/science/article/pii/")
            else:
                raise ValueError
        except ValueError:
            raise FetchDenied("sciencedirect_identifier_denied") from None
    if expected_kind != "doi" and re.fullmatch(r"(?:S[A-Z0-9]{16}|B[A-Z0-9]{19})", value):
        return ArticleIdentifier(kind="pii", value=value)
    if (
        expected_kind != "pii"
        and len(value) <= 256
        and re.fullmatch(r"10\.[0-9]{4,9}/[A-Za-z0-9._;()/:-]+", value)
        and not any(segment in ("", ".", "..") for segment in value.split("/"))
    ):
        return ArticleIdentifier(kind="doi", value=value.lower())
    raise FetchDenied("sciencedirect_identifier_denied")


def article_path(identifier: ArticleIdentifier) -> str:
    checked = normalize_identifier(identifier.value)
    if checked != identifier:
        raise FetchDenied("sciencedirect_identifier_denied")
    return f"/content/article/{checked.kind}/{quote(checked.value, safe='/')}"


class SearchAuthor(Contract):
    order: int = Field(ge=0, le=199)
    name: str = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def name_text(cls, value: str) -> str:
        return _text(value)


class SearchArticle(Contract):
    pii: str | None
    doi: str | None
    title: str = Field(min_length=1, max_length=2000)
    source_title: str | None = Field(default=None, max_length=1000)
    publication_date: str | None = Field(default=None, max_length=40)
    authors: tuple[SearchAuthor, ...] = Field(max_length=200)
    contact_status: Literal["not_available_in_search"] = "not_available_in_search"
    # A digest + row locator traces metadata only, never correspondence evidence.
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(pattern=r"^/results/[0-9]{1,3}$")

    @property
    def identity(self) -> str:
        return f"pii:{self.pii}" if self.pii else f"doi:{self.doi}"


class SearchPage(Contract):
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: SearchRequest
    reported_total: int = Field(ge=0, le=1_000_000_000)
    articles: tuple[SearchArticle, ...] = Field(max_length=100)
    raw_entries: int = Field(ge=0, le=100)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError("nonfinite_json")


def _float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("nonfinite_json")
    return parsed


def _load(payload: bytes) -> object:
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_BYTES:
        raise FetchDenied("sciencedirect_payload_limit")
    # Bound nesting before json.loads (including ignored fields) without evaluating
    # content. JSON decoding subsequently validates the complete grammar.
    depth = 0
    nodes = 0
    string = False
    escaped = False
    for byte in payload:
        if string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                string = False
        elif byte == 34:
            string = True
            nodes += 1
        elif byte in (91, 123):
            depth += 1
            nodes += 1
            if depth > MAX_DEPTH:
                raise FetchDenied("sciencedirect_payload_limit")
        elif byte in (93, 125):
            depth -= 1
        elif byte == 44:
            nodes += 1
        if nodes > MAX_NODES:
            raise FetchDenied("sciencedirect_payload_limit")
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
    except (ValueError, RecursionError):
        raise FetchDenied("sciencedirect_payload_invalid") from None


def _optional_text(row: dict[str, object], key: str, limit: int) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid_field")
    return _text(value)


def _article(row: object, index: int, digest: str) -> SearchArticle:
    if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
        raise ValueError("invalid_article")
    pii = _optional_text(row, "pii", 256)
    doi = _optional_text(row, "doi", 256)
    for kind, value in (("pii", pii), ("doi", doi)):
        if value is not None and (
            value.startswith("https://") or normalize_identifier(value).kind != kind
        ):
            raise ValueError("invalid_identifier")
    if pii is None and doi is None:
        raise ValueError("missing_identifier")
    title = _optional_text(row, "title", 2000)
    if title is None:
        raise ValueError("missing_title")
    authors = row.get("authors", [])
    if not isinstance(authors, list) or len(authors) > 200:
        raise ValueError("invalid_authors")
    parsed = tuple(SearchAuthor.model_validate(author) for author in authors)
    if len({author.order for author in parsed}) != len(parsed):
        raise ValueError("ambiguous_author_order")
    return SearchArticle(
        pii=pii,
        doi=normalize_identifier(doi).value if doi else None,
        title=title,
        source_title=_optional_text(row, "sourceTitle", 1000),
        publication_date=_optional_text(row, "publicationDate", 40),
        authors=tuple(sorted(parsed, key=lambda author: author.order)),
        locator=f"/results/{index}",
        payload_sha256=digest,
    )


def parse_search(payload: bytes, request: SearchRequest) -> SearchPage:
    """Parse response bytes, never request/follow the untrusted `uri` field.

    Unknown metadata is ignored. There is no first/corresponding-author inference,
    no contact extraction and no source count/completeness guarantee here.
    """
    data = _load(payload)
    try:
        if not isinstance(data, dict):
            raise ValueError("invalid_root")
        if data.get("message") not in (None, ""):
            raise ValueError("provider_message_requires_review")
        total, rows = data.get("resultsFound"), data.get("results")
        if type(total) is not int or not 0 <= total <= 1_000_000_000:
            raise ValueError("invalid_total")
        if not isinstance(rows, list) or len(rows) > request.show:
            raise ValueError("invalid_results")
        digest = hashlib.sha256(payload).hexdigest()
        articles = tuple(_article(row, index, digest) for index, row in enumerate(rows))
        if total < request.offset + len(rows):
            raise ValueError("inconsistent_total")
        return SearchPage(
            payload_sha256=digest,
            request=request,
            reported_total=total,
            articles=articles,
            raw_entries=len(rows),
        )
    except (ValueError, ValidationError, FetchDenied):
        raise FetchDenied("sciencedirect_response_invalid") from None


class DiscoveryState(Contract):
    request: SearchRequest
    max_pages: int = Field(default=10, ge=1, le=100)
    max_articles: int = Field(default=100, ge=1, le=500)
    pages: int = Field(default=0, ge=0, le=100)
    articles: tuple[SearchArticle, ...] = Field(default=(), max_length=500)
    digests: tuple[str, ...] = Field(default=(), max_length=100)
    reported_total: int | None = None
    status: Literal["pending", "completed", "partial"] = "pending"
    reason: Literal[
        "pending",
        "reported_exhausted",
        "page_cap",
        "article_cap",
        "source_cap",
        "repeated_page",
        "no_new_results",
        "inconsistent_page",
        "conflicting_identity",
    ] = "pending"


def advance(state: DiscoveryState, page: SearchPage) -> DiscoveryState:
    """Pure bounded pagination; caller retains tenant/job-bound state privately."""
    if (
        state.status != "pending"
        or page.request != state.request
        or state.pages != len(state.digests)
        or state.pages >= state.max_pages
        or len(state.articles) > state.max_articles
    ):
        raise FetchDenied("sciencedirect_checkpoint_denied")
    updates: dict[str, object] = {"pages": state.pages + 1, "reported_total": page.reported_total}
    reason = "pending"
    if page.payload_sha256 in state.digests:
        reason = "repeated_page"
    elif state.reported_total is not None and state.reported_total != page.reported_total:
        reason = "inconsistent_page"
    articles = list(state.articles)
    additions = 0
    overflow = False
    if reason == "pending":
        for item in page.articles:
            matches = [
                index
                for index, known in enumerate(articles)
                if (
                    item.pii is not None
                    and item.pii == known.pii
                    or item.doi is not None
                    and item.doi == known.doi
                )
            ]
            if matches:
                known = articles[matches[0]]
                if len(matches) > 1 or (
                    item.pii is not None
                    and known.pii is not None
                    and item.pii != known.pii
                    or item.doi is not None
                    and known.doi is not None
                    and item.doi != known.doi
                ):
                    reason = "conflicting_identity"
                    break
                # Prefer a single more complete observed row, not merged fields
                # without their own provenance. Neither row grants contact roles.
                if (
                    known.pii is None
                    and item.pii is not None
                    or known.doi is None
                    and item.doi is not None
                ):
                    articles[matches[0]] = item
                continue
            if len(articles) >= state.max_articles:
                overflow = True
                break
            articles.append(item)
            additions += 1
        end = state.request.offset + page.raw_entries
        if reason == "conflicting_identity":
            articles = list(state.articles)
        elif overflow:
            reason = "article_cap"
        elif page.raw_entries == 0 and end < page.reported_total:
            reason = "inconsistent_page"
        elif page.raw_entries > 0 and additions == 0:
            reason = "no_new_results"
        elif end >= page.reported_total:
            reason = "reported_exhausted"
        elif len(articles) >= state.max_articles:
            reason = "article_cap"
        elif state.pages + 1 >= state.max_pages:
            reason = "page_cap"
        elif end > 6000:
            reason = "source_cap"
        elif page.raw_entries < state.request.show:
            reason = "inconsistent_page"
        else:
            updates["request"] = SearchRequest(
                query=state.request.query,
                offset=end,
                show=state.request.show,
                sort_by=state.request.sort_by,
            )
    updates.update(
        articles=tuple(articles),
        digests=(*state.digests, page.payload_sha256),
        reason=reason,
        status="completed"
        if reason == "reported_exhausted"
        else "pending"
        if reason == "pending"
        else "partial",
    )
    return DiscoveryState.model_validate({**state.model_dump(), **updates})
