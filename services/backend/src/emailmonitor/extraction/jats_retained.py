"""Typed retained Open Access JATS facts (OA-029, document 91).

The isolated parser's ``JatsObservation`` names the Europe PMC full-text URL as its
``url``. The retained record keeps that as ``canonical_url`` provenance and uses
the registered synthetic article path as its durable ``url``, exactly as the XML
route does. Only registered documents, their pinned digests and the lease binding
can produce a record; the database guard re-checks every one of these fields.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from emailmonitor.extraction.html import AuthorFact, Fact, MetadataValues
from emailmonitor.extraction.jats import JatsCandidateFact, JatsObservation
from emailmonitor.extraction.xml_retained import MAX_ENVELOPE, XmlBinding
from emailmonitor.sources.open_access_documents import BY_URL, OpenAccessDocument
from emailmonitor.sources.openaccess import LicenseCategory, PmcIdentifier, license_category

JatsReason = Literal["authors_truncated"]
# Keywords are untrusted article text; the database guard enforces the same bound.
MAX_KEYWORD = 300


class RetainedJats(Fact):
    schema_version: Literal["1.0"] = "1.0"
    parser_version: Literal["open-access-jats-v2"] = "open-access-jats-v2"
    route: Literal["jats_xml"] = "jats_xml"
    full_text_provider: Literal["europe-pmc"] = "europe-pmc"
    url: str = Field(max_length=2048)
    canonical_url: str = Field(max_length=2048)
    requested_identifier: PmcIdentifier
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "partial", "unsupported"]
    reasons: list[JatsReason] = Field(default_factory=list, max_length=4)
    article_pmcid: str | None = Field(default=None, pattern=r"^PMC\d{1,12}$")
    keywords: list[Annotated[str, Field(max_length=MAX_KEYWORD)]] = Field(
        default_factory=list, max_length=50
    )
    license_url: str | None = Field(default=None, max_length=2048)
    # Owner decision 2026-11-19 ("allow but flag"): kept with the observation.
    license_category: LicenseCategory
    authors: list[AuthorFact] = Field(default_factory=list, max_length=100)
    candidates: list[JatsCandidateFact] = Field(default_factory=list, max_length=100)
    preferred_metadata: MetadataValues = Field(default_factory=MetadataValues)
    binding: XmlBinding
    excerpts_retained: bool
    isolation_profile: Literal["network-none-parser-v1"] = "network-none-parser-v1"
    identity_association_implemented: Literal[False] = False

    @model_validator(mode="after")
    def retained_integrity(self) -> RetainedJats:
        document = BY_URL.get(self.url)
        if (
            document is None
            or self.canonical_url != document.canonical_url
            or self.requested_identifier != document.identifier
            or self.content_digest != document.content_digest
            or self.acquisition_digest != document.content_digest
            or (self.article_pmcid is not None and self.article_pmcid != document.pmcid)
            or self.license_category != license_category(self.license_url)
        ):
            raise ValueError("Registered Open Access document provenance required")
        if [a.position for a in self.authors] != list(range(1, len(self.authors) + 1)) or any(
            a.first != (a.position == 1) for a in self.authors
        ):
            raise ValueError("Observed author order required")
        positions = {a.position for a in self.authors}
        evidence = [e for a in self.authors for e in a.evidence]
        for candidate in self.candidates:
            if (
                len(set(candidate.author_positions)) != len(candidate.author_positions)
                or not set(candidate.author_positions) <= positions
                or (
                    self.excerpts_retained
                    and candidate.raw_address not in candidate.evidence.excerpt
                )
            ):
                raise ValueError("Retained JATS structural evidence required")
            evidence.append(candidate.evidence)
        if any(
            not e.locator
            or e.kind != "structured_metadata"
            or bool(e.excerpt) != self.excerpts_retained
            for e in evidence
        ):
            raise ValueError("Consistent retained JATS evidence required")
        if self.status == "unsupported":
            if self.authors or self.candidates:
                raise ValueError("Unsupported outcome cannot assert facts")
        elif not self.authors:
            raise ValueError("Supported outcome requires authors")
        if self.status in ("observed", "no_contact", "unsupported") and self.reasons:
            raise ValueError("Complete outcome cannot carry partial reasons")
        if self.status == "partial" and not self.reasons:
            raise ValueError("Partial outcome needs reasons")
        if self.status in ("observed", "no_contact") and (
            (self.status == "observed") != bool(self.candidates)
        ):
            raise ValueError("Complete outcome must agree with facts")
        return self


def retain_jats(
    observed: JatsObservation,
    document: OpenAccessDocument,
    binding: XmlBinding,
    excerpts: bool,
) -> RetainedJats:
    """Bind an isolated parse to its registered document and the current lease."""
    observed = JatsObservation.model_validate_json(observed.model_dump_json())
    if (
        BY_URL.get(document.source_url) != document
        or observed.requested_identifier != document.identifier
        or observed.content_digest != document.content_digest
        or observed.url != document.canonical_url
    ):
        raise ValueError("Registered Open Access document required")
    if observed.candidates and not observed.authors:
        raise ValueError("Addresses without observed authors cannot be retained")
    status: str = observed.status
    reasons: list[str] = []
    if observed.authors_truncated and status != "unsupported":
        status, reasons = "partial", ["authors_truncated"]
    record: dict[str, object] = {
        "url": document.source_url,
        "canonical_url": observed.url,
        "requested_identifier": observed.requested_identifier.model_dump(mode="json"),
        "content_digest": observed.content_digest,
        "acquisition_digest": observed.content_digest,
        "status": status,
        "reasons": reasons,
        "article_pmcid": observed.article_pmcid,
        "keywords": [keyword[:MAX_KEYWORD] for keyword in observed.keywords],
        "license_url": observed.license_url,
        "license_category": license_category(observed.license_url),
        "authors": [a.model_dump(mode="json") for a in observed.authors],
        "candidates": [c.model_dump(mode="json") for c in observed.candidates],
        "preferred_metadata": {
            "title": observed.title,
            "journal": observed.journal,
            "publication_date": observed.publication_date,
            "doi": observed.doi,
        },
        "binding": binding.model_dump(mode="json"),
        "excerpts_retained": excerpts and bool(observed.authors or observed.candidates),
    }

    def strip(value: object) -> None:
        if isinstance(value, dict):
            if "excerpt" in value:
                value["excerpt"] = ""
            for child in value.values():
                strip(child)
        elif isinstance(value, list):
            for child in value:
                strip(child)

    if not excerpts:
        strip(record)
    result = RetainedJats.model_validate_json(json.dumps(record))
    if len(result.model_dump_json().encode()) > MAX_ENVELOPE:
        raise ValueError("Retained JATS envelope exceeds bounded ceiling")
    return result
