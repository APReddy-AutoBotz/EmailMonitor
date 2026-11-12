"""Crossref REST API connector and Open Access metadata resolver.

Resolves DOIs, extracts author sequence (first vs additional), ORCID identifiers,
institutional affiliations, and direct text-mining XML/PDF links.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from emailmonitor.sources.openaccess import DoiIdentifier

CROSSREF_API_HOST = "api.crossref.org"
MAX_ROWS = 100
DEFAULT_ROWS = 25


class CrossrefAuthor(BaseModel):
    """Author metadata parsed from Crossref work response."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    given: str = Field(default="", max_length=200)
    family: str = Field(default="", max_length=200)
    sequence: str = Field(default="additional", pattern=r"^(first|additional)$")
    orcid: str | None = Field(default=None, max_length=200)
    affiliations: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def display_name(self) -> str:
        if self.given and self.family:
            return f"{self.given} {self.family}".strip()
        return (self.family or self.given or "Unknown Author").strip()

    @property
    def is_first_author(self) -> bool:
        return self.sequence == "first"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrossrefAuthor:
        affiliations = tuple(
            aff["name"].strip()
            for aff in data.get("affiliation", [])
            if (
                isinstance(aff, dict)
                and "name" in aff
                and isinstance(aff["name"], str)
                and aff["name"].strip()
            )
        )
        orcid_val = data.get("ORCID")
        if isinstance(orcid_val, str) and orcid_val.strip():
            orcid = orcid_val.strip()
        else:
            orcid = None

        return cls(
            given=str(data.get("given", "")).strip(),
            family=str(data.get("family", "")).strip(),
            sequence=str(data.get("sequence", "additional")).strip(),
            orcid=orcid,
            affiliations=affiliations,
        )


class CrossrefFullTextLink(BaseModel):
    """Direct full-text artifact link declared by publisher in Crossref."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    url: str = Field(max_length=2048)
    content_type: str = Field(max_length=100)
    application: str = Field(default="text-mining", max_length=100)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlsplit(v)
        if parsed.scheme != "https":
            raise ValueError("Crossref full text URL must use secure HTTPS")
        return v

    @property
    def is_xml(self) -> bool:
        return any(x in self.content_type.lower() for x in ("xml", "jats"))

    @property
    def is_pdf(self) -> bool:
        return "pdf" in self.content_type.lower()


class CrossrefWork(BaseModel):
    """Parsed scholarly work from Crossref metadata."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    doi: DoiIdentifier
    title: str = Field(default="Untitled Work", max_length=1000)
    container_title: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    publication_year: int | None = Field(default=None, ge=1900, le=2100)
    citation_count: int = Field(default=0, ge=0)
    authors: tuple[CrossrefAuthor, ...] = Field(default_factory=tuple)
    full_text_links: tuple[CrossrefFullTextLink, ...] = Field(default_factory=tuple)
    is_open_access: bool = Field(default=False)

    @property
    def first_author(self) -> CrossrefAuthor | None:
        for author in self.authors:
            if author.is_first_author:
                return author
        return self.authors[0] if self.authors else None

    @property
    def xml_full_text_url(self) -> str | None:
        for link in self.full_text_links:
            if link.is_xml:
                return link.url
        return None

    @property
    def pdf_full_text_url(self) -> str | None:
        for link in self.full_text_links:
            if link.is_pdf:
                return link.url
        return None

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> CrossrefWork:
        doi = DoiIdentifier(value=item["DOI"])
        titles = item.get("title", [])
        title = titles[0].strip() if titles and isinstance(titles[0], str) else "Untitled Work"

        containers = item.get("container-title", [])
        container = containers[0].strip() if containers and isinstance(containers[0], str) else None

        publisher = item.get("publisher")
        if isinstance(publisher, str):
            publisher = publisher.strip()
        else:
            publisher = None

        # Extract publication year
        year: int | None = None
        for date_key in ("published-online", "published-print", "issued", "created"):
            date_info = item.get(date_key)
            if isinstance(date_info, dict):
                parts = date_info.get("date-parts")
                if parts and isinstance(parts, list) and parts[0] and isinstance(parts[0], list):
                    try:
                        y = int(parts[0][0])
                        if 1900 <= y <= 2100:
                            year = y
                            break
                    except (ValueError, TypeError):
                        pass

        # Authors
        authors = tuple(
            CrossrefAuthor.from_dict(a)
            for a in item.get("author", [])
            if isinstance(a, dict)
        )

        # Full-text links
        links: list[CrossrefFullTextLink] = []
        for lk in item.get("link", []):
            if isinstance(lk, dict) and "URL" in lk and "content-type" in lk:
                try:
                    links.append(
                        CrossrefFullTextLink(
                            url=str(lk["URL"]),
                            content_type=str(lk["content-type"]),
                            application=str(lk.get("intended-application", "text-mining")),
                        )
                    )
                except ValueError:
                    continue

        # Open access check via license
        licenses = item.get("license", [])
        is_oa = any(
            isinstance(lic, dict)
            and any(
                cc in str(lic.get("URL", "")).lower()
                for cc in ("creativecommons", "cc-by", "open-access")
            )
            for lic in licenses
        )

        return cls(
            doi=doi,
            title=title,
            container_title=container,
            publisher=publisher,
            publication_year=year,
            citation_count=int(item.get("is-referenced-by-count", 0)),
            authors=authors,
            full_text_links=tuple(links),
            is_open_access=is_oa,
        )


class CrossrefQueryPlanner(BaseModel):
    """Constructs deterministic, safe Crossref REST API query URLs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=500)
    rows: int = Field(default=DEFAULT_ROWS, ge=1, le=MAX_ROWS)
    open_access_only: bool = Field(default=True)
    from_year: int | None = Field(default=None, ge=1900, le=2100)
    until_year: int | None = Field(default=None, ge=1900, le=2100)

    def plan_url(self) -> str:
        params: dict[str, str] = {
            "query": self.query,
            "rows": str(self.rows),
            "sort": "relevance",
            "order": "desc",
        }
        filters: list[str] = ["type:journal-article"]
        if self.open_access_only:
            filters.append("has-license:true")
        if self.from_year:
            filters.append(f"from-pub-date:{self.from_year}-01-01")
        if self.until_year:
            filters.append(f"until-pub-date:{self.until_year}-12-31")

        params["filter"] = ",".join(filters)
        return f"https://{CROSSREF_API_HOST}/works?{urlencode(params)}"


class CrossrefFixtureGateway:
    """Offline test gateway serving committed Crossref work fixtures."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._path = fixture_path or (
            Path(__file__).parents[5] / "fixtures" / "crossref" / "works-crispr.json"
        )

    def search_works(self, planner: CrossrefQueryPlanner) -> tuple[CrossrefWork, ...]:
        if not self._path.exists():
            raise FileNotFoundError(f"Missing Crossref test fixture at {self._path}")
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)

        items = data.get("message", {}).get("items", [])
        works = [CrossrefWork.from_item(item) for item in items]
        if planner.open_access_only:
            works = [w for w in works if w.is_open_access]
        return tuple(works[: planner.rows])

    def resolve_doi(self, doi: str) -> CrossrefWork | None:
        clean_doi = DoiIdentifier(value=doi)
        works = self.search_works(CrossrefQueryPlanner(query="*", open_access_only=False))
        for work in works:
            if work.doi.value == clean_doi.value:
                return work
        return None
