"""Europe PMC REST search planner and bounded result parser.

Europe PMC's ``/search`` endpoint is the keyword -> PMCID bridge for the
Open Access pipeline: a hit carrying a PMCID that is open access and present
in Europe PMC can be retrieved as full-text JATS XML through the separate
``fullTextXML`` boundary. This module only plans URLs and parses supplied
response bytes. It never performs network I/O; the response body is untrusted
data and can never change permissions, routing or limits.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator

from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import DOI_PATTERN

EUROPE_PMC_SEARCH_URL: Literal["https://www.ebi.ac.uk/europepmc/webservices/rest/search"] = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)
MAX_PAGE_SIZE = 100
MAX_PAYLOAD_BYTES = 5_242_880
MAX_QUERY_LENGTH = 1_000
_PMCID = re.compile(r"^PMC\d{3,10}$")
_YEAR = re.compile(r"^(1[89]\d\d|20\d\d|2100)$")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EuropePmcSearchRequest(Contract):
    """Bounded keyword/Boolean search. Filters are request syntax, not permission."""

    query: Annotated[str, Field(min_length=1, max_length=MAX_QUERY_LENGTH)]
    page_size: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)
    cursor_mark: Annotated[str, Field(min_length=1, max_length=512)] = "*"
    open_access_only: bool = True
    full_text_in_epmc_only: bool = True
    from_year: int | None = Field(default=None, ge=1800, le=2100)
    until_year: int | None = Field(default=None, ge=1800, le=2100)

    @field_validator("query")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or any(ord(c) < 32 or ord(c) == 127 for c in stripped):
            raise ValueError("invalid_query_text")
        return stripped

    def effective_query(self) -> str:
        clauses = [f"({self.query})"]
        if self.open_access_only:
            clauses.append("OPEN_ACCESS:y")
        if self.full_text_in_epmc_only:
            clauses.append("IN_EPMC:y")
        if self.from_year is not None or self.until_year is not None:
            low = self.from_year if self.from_year is not None else 1800
            high = self.until_year if self.until_year is not None else 2100
            if low > high:
                raise FetchDenied("invalid_year_range")
            clauses.append(f"PUB_YEAR:[{low} TO {high}]")
        return " AND ".join(clauses)

    def plan_url(self) -> str:
        params = {
            "query": self.effective_query(),
            "format": "json",
            "resultType": "lite",
            "pageSize": str(self.page_size),
            "cursorMark": self.cursor_mark,
        }
        return f"{EUROPE_PMC_SEARCH_URL}?{urlencode(params)}"


def doi_lookup_request(doi: str) -> EuropePmcSearchRequest:
    """Plan an exact-DOI lookup used to resolve a Crossref/OpenAlex DOI to a PMCID."""
    cleaned = doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    if not DOI_PATTERN.match(cleaned):
        raise FetchDenied("invalid_doi_format")
    return EuropePmcSearchRequest(
        query=f'DOI:"{cleaned}"',
        page_size=1,
        open_access_only=False,
        full_text_in_epmc_only=False,
    )


class EuropePmcHit(Contract):
    """One search result. Absent fields stay absent; nothing is defaulted."""

    source_id: Annotated[str, Field(min_length=1, max_length=64)]
    source: Annotated[str, Field(min_length=1, max_length=16)]
    pmid: str | None = Field(default=None, max_length=32)
    pmcid: str | None = Field(default=None, pattern=r"^PMC\d{3,10}$")
    doi: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=1000)
    author_string: str | None = Field(default=None, max_length=4000)
    journal_title: str | None = Field(default=None, max_length=500)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    first_publication_date: str | None = Field(default=None, max_length=32)
    is_open_access: bool = False
    in_epmc: bool = False
    has_pdf: bool = False

    @property
    def full_text_xml_available(self) -> bool:
        """Europe PMC serves fullTextXML only for OA articles held in Europe PMC."""
        return self.pmcid is not None and self.is_open_access and self.in_epmc


class EuropePmcSearchPage(Contract):
    hit_count: int = Field(ge=0)
    hits: tuple[EuropePmcHit, ...] = Field(default_factory=tuple, max_length=MAX_PAGE_SIZE)
    next_cursor_mark: str | None = Field(default=None, max_length=512)

    @property
    def exhausted(self) -> bool:
        return self.next_cursor_mark is None or not self.hits


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned[:limit]


def _flag(value: object) -> bool:
    return isinstance(value, str) and value.strip().upper() == "Y"


def parse_hit(item: dict[str, object]) -> EuropePmcHit | None:
    """Parse one result; returns None for records without a usable identifier."""
    source_id = _text(item.get("id"), 64)
    source = _text(item.get("source"), 16)
    if source_id is None or source is None:
        return None
    pmcid_raw = _text(item.get("pmcid"), 16)
    pmcid = pmcid_raw.upper() if pmcid_raw and _PMCID.match(pmcid_raw.upper()) else None
    doi_raw = _text(item.get("doi"), 256)
    doi = doi_raw.lower() if doi_raw and DOI_PATTERN.match(doi_raw.lower()) else None
    year_raw = _text(item.get("pubYear"), 4)
    year = int(year_raw) if year_raw and _YEAR.match(year_raw) else None
    return EuropePmcHit(
        source_id=source_id,
        source=source,
        pmid=_text(item.get("pmid"), 32),
        pmcid=pmcid,
        doi=doi,
        title=_text(item.get("title"), 1000),
        author_string=_text(item.get("authorString"), 4000),
        journal_title=_text(item.get("journalTitle"), 500),
        publication_year=year,
        first_publication_date=_text(item.get("firstPublicationDate"), 32),
        is_open_access=_flag(item.get("isOpenAccess")),
        in_epmc=_flag(item.get("inEPMC")),
        has_pdf=_flag(item.get("hasPDF")),
    )


def parse_search_response(data: bytes | str) -> EuropePmcSearchPage:
    """Parse a Europe PMC JSON search response under fixed byte and item ceilings."""
    if isinstance(data, bytes):
        if len(data) > MAX_PAYLOAD_BYTES:
            raise FetchDenied("europe_pmc_search_payload_too_large")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise FetchDenied("invalid_europe_pmc_search_encoding") from None
    else:
        if len(data.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise FetchDenied("europe_pmc_search_payload_too_large")
        text = data
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        raise FetchDenied("invalid_europe_pmc_search_json") from None
    if not isinstance(payload, dict):
        raise FetchDenied("invalid_europe_pmc_search_structure")
    result_list = payload.get("resultList")
    results = result_list.get("result") if isinstance(result_list, dict) else None
    if not isinstance(results, list):
        raise FetchDenied("missing_europe_pmc_result_list")
    raw_count = payload.get("hitCount")
    hit_count = raw_count if isinstance(raw_count, int) and raw_count >= 0 else 0
    hits: list[EuropePmcHit] = []
    for item in results[:MAX_PAGE_SIZE]:
        if isinstance(item, dict):
            hit = parse_hit(item)
            if hit is not None:
                hits.append(hit)
    next_cursor = _text(payload.get("nextCursorMark"), 512)
    return EuropePmcSearchPage(
        hit_count=max(hit_count, len(hits)),
        hits=tuple(hits),
        next_cursor_mark=next_cursor,
    )


def _query_terms(query: str) -> tuple[str, ...]:
    stripped = re.sub(r"\b(AND|OR|NOT)\b", " ", query)
    return tuple(t for t in re.findall(r"[a-z0-9][a-z0-9-]*", stripped.lower()) if len(t) > 2)


class EuropePmcSearchFixtureGateway:
    """Offline stand-in for the search endpoint over a committed synthetic page.

    Matching is a deliberately simple fixture rule (any query term in the title,
    or an exact DOI clause); it does not emulate Europe PMC relevance ranking.
    """

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._path = fixture_path or (
            Path(__file__).resolve().parents[5] / "fixtures" / "europepmc" / "search-crispr.json"
        )

    def _all_hits(self) -> tuple[EuropePmcHit, ...]:
        if not self._path.is_file():
            raise FetchDenied("missing_europe_pmc_search_fixture")
        return parse_search_response(self._path.read_bytes()).hits

    def search(self, request: EuropePmcSearchRequest) -> EuropePmcSearchPage:
        hits = self._all_hits()
        doi_clause = re.fullmatch(r'DOI:"([^"]+)"', request.query)
        selected: Iterable[EuropePmcHit]
        if doi_clause:
            wanted = doi_clause.group(1).lower()
            selected = [h for h in hits if h.doi == wanted]
        else:
            terms = _query_terms(request.query)
            selected = [
                h
                for h in hits
                if h.title and (not terms or any(t in h.title.lower() for t in terms))
            ]
        filtered = [
            h
            for h in selected
            if (not request.open_access_only or h.is_open_access)
            and (not request.full_text_in_epmc_only or h.in_epmc)
            and (
                request.from_year is None
                or (h.publication_year is not None and h.publication_year >= request.from_year)
            )
            and (
                request.until_year is None
                or (h.publication_year is not None and h.publication_year <= request.until_year)
            )
        ]
        page = tuple(filtered[: request.page_size])
        return EuropePmcSearchPage(hit_count=len(filtered), hits=page, next_cursor_mark=None)

    def resolve_doi(self, doi: str) -> EuropePmcHit | None:
        page = self.search(doi_lookup_request(doi))
        return page.hits[0] if page.hits else None
