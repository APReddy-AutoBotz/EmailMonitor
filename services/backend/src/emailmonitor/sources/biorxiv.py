"""bioRxiv and medRxiv Pre-Print REST Connector and Metadata Resolver.

Provides structured query planning, preprint publication metadata parsing,
corresponding author identification, and direct JATS XML source routing
for rapid discovery of active manuscripts prior to journal publication.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.sources.openaccess import DoiIdentifier

PreprintServer = Literal["biorxiv", "medrxiv"]

MAX_PREPRINTS_PER_REQUEST = 100


class Contract(BaseModel):
    """Base immutable contract with forbidden unknown attributes."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BioRxivQueryPlanner(Contract):
    """Builds bounded, normalized query parameters for bioRxiv/medRxiv API endpoints."""

    server: PreprintServer = "biorxiv"
    from_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    to_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=MAX_PREPRINTS_PER_REQUEST)

    @property
    def api_path(self) -> str:
        """Generate canonical bioRxiv API path: /details/[server]/[from_date]/[to_date]/[cursor]."""
        return f"/details/{self.server}/{self.from_date}/{self.to_date}/{self.cursor}"

    @property
    def canonical_url(self) -> str:
        """Generate full canonical endpoint URL."""
        return f"https://api.biorxiv.org{self.api_path}"


class BioRxivPreprint(Contract):
    """Normalized scholarly preprint work observed from bioRxiv or medRxiv."""

    doi: DoiIdentifier
    title: str
    authors: tuple[str, ...]
    corresponding_author: str | None = None
    corresponding_institution: str | None = None
    posted_date: Annotated[str, Field(pattern=r"^(19|20)\d\d-\d{2}-\d{2}$")]
    version: int = Field(ge=1, le=50)
    server: PreprintServer
    category: str
    license_type: str | None = None
    jats_xml_url: str | None = None
    abstract_text: str | None = None

    @property
    def publication_year(self) -> int:
        """Calendar year of the posted date (validated as YYYY-MM-DD on parse)."""
        return int(self.posted_date[:4])


def parse_biorxiv_api_response(raw_json: str | bytes) -> tuple[BioRxivPreprint, ...]:
    """Parse raw bioRxiv/medRxiv JSON response into immutable preprint models."""
    data = json.loads(raw_json)
    if not isinstance(data, dict):
        raise ValueError("Invalid bioRxiv API payload: root must be a JSON object")

    collection = data.get("collection", [])
    if not isinstance(collection, list):
        raise ValueError("Invalid bioRxiv API payload: 'collection' must be a list")

    preprints: list[BioRxivPreprint] = []
    for item in collection:
        if not isinstance(item, dict):
            continue

        raw_doi = item.get("doi", "").strip()
        if not raw_doi:
            continue

        doi = DoiIdentifier(value=raw_doi)
        title = item.get("title", "").strip() or "Untitled Preprint"

        raw_authors = item.get("authors", "")
        author_list = [a.strip() for a in re.split(r"[;,]", raw_authors) if a.strip()]

        # A missing corresponding-author field stays unknown; it is never
        # back-filled with the first author.
        corresp = str(item.get("author_corresponding") or "").strip() or None

        inst = item.get("author_corresponding_institution", "").strip() or None
        date_str = str(item.get("date") or "").strip()
        if not re.fullmatch(r"(19|20)\d\d-\d{2}-\d{2}", date_str):
            continue  # an undated record is not given an invented date
        raw_version = item.get("version", "1")
        try:
            ver_num = int(raw_version)
        except (ValueError, TypeError):
            ver_num = 1

        srv_raw = item.get("server", "biorxiv").lower()
        srv: PreprintServer = "medrxiv" if "med" in srv_raw else "biorxiv"
        cat = item.get("category", "biology").strip()
        lic = item.get("license", "").strip() or None
        jats = item.get("jatsxml", "").strip() or None
        abstract = item.get("abstract", "").strip() or None

        preprints.append(
            BioRxivPreprint(
                doi=doi,
                title=title,
                authors=tuple(author_list),
                corresponding_author=corresp,
                corresponding_institution=inst,
                posted_date=date_str,
                version=ver_num,
                server=srv,
                category=cat,
                license_type=lic,
                jats_xml_url=jats,
                abstract_text=abstract,
            )
        )

    return tuple(preprints)


class BioRxivFixtureGateway:
    """Offline gateway serving synthetic bioRxiv and medRxiv preprint fixtures."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._path = fixture_path or (
            Path(__file__).parents[5] / "fixtures" / "biorxiv" / "recent-crispr.json"
        )

    def search_preprints(self, planner: BioRxivQueryPlanner) -> tuple[BioRxivPreprint, ...]:
        """Load and filter offline preprints matching date bounds and server."""
        if not self._path.exists():
            raise FileNotFoundError(f"Missing bioRxiv test fixture at {self._path}")

        with open(self._path, encoding="utf-8") as f:
            all_preprints = parse_biorxiv_api_response(f.read())

        matched = [
            p
            for p in all_preprints
            if p.server == planner.server and planner.from_date <= p.posted_date <= planner.to_date
        ]

        start = planner.cursor
        end = start + planner.limit
        return tuple(matched[start:end])

    def resolve_doi(self, doi: DoiIdentifier) -> BioRxivPreprint | None:
        """Resolve a single preprint by DOI."""
        if not self._path.exists():
            raise FileNotFoundError(f"Missing bioRxiv test fixture at {self._path}")

        with open(self._path, encoding="utf-8") as f:
            all_preprints = parse_biorxiv_api_response(f.read())

        for p in all_preprints:
            if p.doi.value.lower() == doi.value.lower():
                return p
        return None


def matches_keywords(preprint: BioRxivPreprint, query: str) -> bool:
    """Client-side keyword rule: every query term appears in title, abstract or category.

    The bioRxiv ``details`` endpoint lists a date window and has no keyword search,
    so the connector must filter locally. Terms shorter than three characters and
    Boolean operators are ignored.
    """
    terms = [
        t
        for t in re.findall(r"[a-z0-9][a-z0-9-]*", re.sub(r"\b(AND|OR|NOT)\b", " ", query).lower())
        if len(t) > 2
    ]
    if not terms:
        return True
    haystack = " ".join(
        part for part in (preprint.title, preprint.abstract_text or "", preprint.category) if part
    ).lower()
    return all(term in haystack for term in terms)


BIORXIV_JATS_MAX_BYTES = 4_194_304


class BioRxivJatsFixtureGateway:
    """Offline stand-in for bioRxiv/medRxiv full-text JATS retrieval keyed by DOI.

    A preprint without a committed synthetic JATS file is reported unavailable;
    the connector never substitutes another article's full text.
    """

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._dir = fixture_dir or (
            Path(__file__).resolve().parents[5] / "fixtures" / "biorxiv" / "jats"
        )

    def fetch_jats(self, doi: DoiIdentifier) -> bytes:
        from emailmonitor.fetching.safety import FetchDenied

        name = doi.value.replace("/", "_") + ".xml"
        if not re.fullmatch(r"10\.1101_[0-9.]+\.xml", name):
            raise FetchDenied("unsupported_preprint_doi")
        path = self._dir / name
        if not path.is_file():
            raise FetchDenied("preprint_full_text_unavailable")
        data = path.read_bytes()
        if len(data) > BIORXIV_JATS_MAX_BYTES:
            raise FetchDenied("preprint_jats_too_large")
        return data
