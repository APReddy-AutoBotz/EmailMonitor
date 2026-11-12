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
    corresponding_author: str
    corresponding_institution: str | None = None
    posted_date: str
    version: int = Field(ge=1, le=50)
    server: PreprintServer
    category: str
    license_type: str | None = None
    jats_xml_url: str | None = None
    abstract_text: str | None = None

    @property
    def publication_year(self) -> int:
        """Extract calendar year from posted date."""
        match = re.search(r"^\d{4}", self.posted_date)
        return int(match.group(0)) if match else 2026


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
        author_list = [
            a.strip()
            for a in re.split(r"[;,]", raw_authors)
            if a.strip()
        ]

        corresp = item.get("author_corresponding", "").strip()
        if not corresp and author_list:
            corresp = author_list[0]

        inst = item.get("author_corresponding_institution", "").strip() or None
        date_str = item.get("date", "2026-01-01").strip()
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
            if p.server == planner.server
            and planner.from_date <= p.posted_date <= planner.to_date
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
