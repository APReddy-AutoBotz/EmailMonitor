"""OpenAlex REST API query planner and work metadata parser.

Bridges Open Access search discovery with full-text JATS XML extraction:
1. Plans bounded search requests (query, filters, ISSN, date ranges).
2. Parses OpenAlex works, capturing corresponding author markers, ORCIDs, and DOIs.
3. Automatically maps works with PMCIDs to PMCID identifiers for direct JATS XML extraction.
"""

import json
import re
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import (
    DoiIdentifier,
    OpenAccessIdentifier,
    OpenAlexIdentifier,
    PmcIdentifier,
)

OPENALEX_API_BASE: Literal["https://api.openalex.org"] = "https://api.openalex.org"
MAX_PAYLOAD_BYTES = 5_242_880  # 5 MB
MAX_WORKS_PER_PAGE = 100

PMC_CLEAN_PATTERN = re.compile(r"PMC\d{3,10}", re.IGNORECASE)
ORCID_CLEAN_PATTERN = re.compile(r"[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class OpenAlexFilter(Contract):
    is_oa: bool = True
    from_publication_date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    to_publication_date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    issn: str | None = Field(default=None, pattern=r"^\d{4}-\d{3}[\dX]$")
    concept_id: str | None = Field(default=None, pattern=r"^c\d{4,12}$")


class OpenAlexSearchRequest(Contract):
    query: Annotated[str, Field(min_length=1, max_length=300)]
    filters: OpenAlexFilter = Field(default_factory=OpenAlexFilter)
    page: int = Field(default=1, ge=1, le=100)
    per_page: int = Field(default=25, ge=1, le=MAX_WORKS_PER_PAGE)
    sort_by: Literal["relevance_score", "publication_date", "cited_by_count"] = (
        "relevance_score"
    )


def build_openalex_query_url(request: OpenAlexSearchRequest) -> str:
    """Build a canonical, safe OpenAlex query URL for searching open access works."""
    params: list[str] = [f"search={quote(request.query)}"]

    filter_tokens: list[str] = []
    if request.filters.is_oa:
        filter_tokens.append("open_access.is_oa:true")
    if request.filters.from_publication_date:
        filter_tokens.append(
            f"from_publication_date:{request.filters.from_publication_date}"
        )
    if request.filters.to_publication_date:
        filter_tokens.append(
            f"to_publication_date:{request.filters.to_publication_date}"
        )
    if request.filters.issn:
        filter_tokens.append(
            f"primary_location.source.issn:{request.filters.issn}"
        )
    if request.filters.concept_id:
        filter_tokens.append(f"concepts.id:{request.filters.concept_id}")

    if filter_tokens:
        params.append("filter=" + quote(",".join(filter_tokens), safe=":,"))

    params.append(f"sort={request.sort_by}:desc")
    params.append(f"page={request.page}")
    params.append(f"per-page={request.per_page}")

    return f"{OPENALEX_API_BASE}/works?" + "&".join(params)


class OpenAlexAuthor(Contract):
    id: str = Field(max_length=256)
    display_name: str = Field(min_length=1, max_length=300)
    orcid: str | None = Field(
        default=None, pattern=r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$"
    )

    @field_validator("orcid", mode="before")
    @classmethod
    def clean_orcid(cls, v: object) -> str | None:
        if isinstance(v, str):
            match = ORCID_CLEAN_PATTERN.search(v)
            if match:
                return match.group(0)
        return None


class OpenAlexAuthorship(Contract):
    author_position: Literal["first", "middle", "last"]
    author: OpenAlexAuthor
    is_corresponding: bool = False
    institutions: list[str] = Field(default_factory=list, max_length=20)


class OpenAlexWork(Contract):
    id: str = Field(max_length=256)
    doi: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=1000)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    publication_date: str | None = Field(default=None, max_length=50)
    journal_title: str | None = Field(default=None, max_length=500)
    issn_l: str | None = Field(default=None, max_length=50)
    is_oa: bool = True
    oa_url: str | None = Field(default=None, max_length=2048)
    pmcid: str | None = Field(
        default=None, pattern=r"^PMC\d{3,10}$"
    )
    pmid: str | None = Field(default=None, max_length=50)
    authorships: list[OpenAlexAuthorship] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("pmcid", mode="before")
    @classmethod
    def clean_pmcid(cls, v: object) -> str | None:
        if isinstance(v, str):
            match = PMC_CLEAN_PATTERN.search(v)
            if match:
                return match.group(0).upper()
        return None


def work_to_open_access_identifier(work: OpenAlexWork) -> OpenAccessIdentifier:
    """Resolve an OpenAlex work into the highest-fidelity OpenAccessIdentifier.

    Prefers PMCID (for full-text JATS XML), then DOI, then OpenAlex work ID.
    """
    if work.pmcid:
        return PmcIdentifier(value=work.pmcid)
    if work.doi:
        return DoiIdentifier(value=work.doi)
    clean_id = work.id.strip().rstrip("/").split("/")[-1].upper()
    return OpenAlexIdentifier(value=clean_id)


def parse_openalex_work(item: dict[str, object]) -> OpenAlexWork:
    """Parse a single OpenAlex work record."""
    work_id = str(item.get("id") or "")
    if not work_id:
        raise FetchDenied("missing_openalex_id")

    doi = str(item.get("doi") or "") or None
    title = str(item.get("title") or "") or None
    pub_year = item.get("publication_year")
    year_val = int(pub_year) if isinstance(pub_year, int) else None
    pub_date = str(item.get("publication_date") or "") or None

    journal_title: str | None = None
    issn_l: str | None = None
    primary_location = item.get("primary_location")
    if isinstance(primary_location, dict):
        source = primary_location.get("source")
        if isinstance(source, dict):
            journal_title = str(source.get("display_name") or "") or None
            issn_l = str(source.get("issn_l") or "") or None

    open_access = item.get("open_access")
    is_oa = True
    oa_url: str | None = None
    if isinstance(open_access, dict):
        is_oa = bool(open_access.get("is_oa", True))
        oa_url = str(open_access.get("oa_url") or "") or None

    ids = item.get("ids")
    pmcid: str | None = None
    pmid: str | None = None
    if isinstance(ids, dict):
        pmcid = str(ids.get("pmcid") or "") or None
        pmid = str(ids.get("pmid") or "") or None

    authorships: list[OpenAlexAuthorship] = []
    raw_authorships = item.get("authorships")
    if isinstance(raw_authorships, list):
        for raw_author in raw_authorships[:100]:
            if not isinstance(raw_author, dict):
                continue
            author_obj = raw_author.get("author")
            if not isinstance(author_obj, dict):
                continue
            a_id = str(author_obj.get("id") or "")
            a_name = str(author_obj.get("display_name") or "")
            a_orcid = str(author_obj.get("orcid") or "") or None
            if not a_name:
                continue

            pos_str = str(raw_author.get("author_position") or "middle").lower()
            if pos_str not in ("first", "middle", "last"):
                pos_str = "middle"

            is_corresp = bool(raw_author.get("is_corresponding", False))

            institutions: list[str] = []
            raw_insts = raw_author.get("institutions")
            if isinstance(raw_insts, list):
                for inst in raw_insts[:20]:
                    if isinstance(inst, dict):
                        dname = str(inst.get("display_name") or "")
                        if dname:
                            institutions.append(dname[:300])

            authorships.append(
                OpenAlexAuthorship(
                    author_position=pos_str,  # type: ignore[arg-type]
                    author=OpenAlexAuthor(
                        id=a_id,
                        display_name=a_name[:300],
                        orcid=a_orcid,
                    ),
                    is_corresponding=is_corresp,
                    institutions=institutions,
                )
            )

    return OpenAlexWork(
        id=work_id,
        doi=doi,
        title=title[:1000] if title else None,
        publication_year=year_val,
        publication_date=pub_date,
        journal_title=journal_title[:500] if journal_title else None,
        issn_l=issn_l,
        is_oa=is_oa,
        oa_url=oa_url,
        pmcid=pmcid,
        pmid=pmid,
        authorships=authorships,
    )


def parse_openalex_search_response(data: bytes | str) -> list[OpenAlexWork]:
    """Parse an OpenAlex API response body into validated OpenAlexWork objects."""
    if isinstance(data, bytes):
        if len(data) > MAX_PAYLOAD_BYTES:
            raise FetchDenied("openalex_payload_too_large")
        raw_text = data.decode("utf-8", errors="replace")
    else:
        raw_text = data

    try:
        payload = json.loads(raw_text)
    except Exception as exc:
        raise FetchDenied(f"invalid_openalex_json: {exc}") from exc

    if not isinstance(payload, dict):
        raise FetchDenied("invalid_openalex_response_structure")

    results = payload.get("results")
    if not isinstance(results, list):
        raise FetchDenied("missing_results_array")

    works: list[OpenAlexWork] = []
    for item in results[:MAX_WORKS_PER_PAGE]:
        if isinstance(item, dict):
            works.append(parse_openalex_work(item))
    return works
