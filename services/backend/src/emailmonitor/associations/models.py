"""Evidence-backed association facts, distinct from mailbox and outreach status."""

import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from emailmonitor.associations.normalization import Address, normalize
from emailmonitor.extraction.html import MetadataValues


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Author(Record):
    id: UUID
    position: int = Field(ge=1, le=100)
    display_name: str = Field(min_length=1, max_length=300)
    first: bool
    corresponding: bool | None
    kind: Literal["person", "group", "unknown"]
    orcid: str | None
    affiliations: tuple[Annotated[str, Field(max_length=1000)], ...] = Field(max_length=20)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)
    identity_state: Literal["article_local_unresolved"] = "article_local_unresolved"


class Evidence(Record):
    id: UUID
    locator: str = Field(min_length=1, max_length=512)
    excerpt: str = Field(max_length=512)
    method: Literal[
        "structured_metadata",
        "article_dom",
        "mailto",
        "public_attribute",
        "browser_dom",
        "pdf_text",
    ]
    page: int | None = Field(default=None, ge=1, le=4)
    anchor: tuple[float, float] | None = None
    region: tuple[float, float, float, float] | None = None
    coordinate_units: Literal["pdf_points"] | None = None
    coordinate_origin: Literal["bottom_left"] | None = None
    region_precision: Literal["full_cropbox_not_glyph_bbox"] | None = None

    @model_validator(mode="after")
    def geometry(self) -> "Evidence":
        if self.method == "pdf_text":
            if (
                self.page is None
                or self.anchor is None
                or self.region is None
                or self.coordinate_units != "pdf_points"
                or self.coordinate_origin != "bottom_left"
                or self.region_precision != "full_cropbox_not_glyph_bbox"
                or not all(math.isfinite(v) for v in (*self.anchor, *self.region))
                or not (self.region[0] < self.region[2] and self.region[1] < self.region[3])
                or not self.region[0] <= self.anchor[0] <= self.region[2]
                or not self.region[1] <= self.anchor[1] <= self.region[3]
            ):
                raise ValueError("Actual coarse PDF geometry/units required")
        elif any(
            v is not None
            for v in (
                self.page,
                self.anchor,
                self.region,
                self.coordinate_units,
                self.coordinate_origin,
                self.region_precision,
            )
        ):
            raise ValueError("HTML evidence cannot manufacture PDF geometry")
        return self


class Candidate(Record):
    id: UUID
    address: Address
    raw_variants: tuple[Annotated[str, Field(min_length=1, max_length=320)], ...] = Field(
        min_length=1, max_length=100
    )
    normalization_collision: bool
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)


class Association(Record):
    id: UUID
    candidate_id: UUID
    author_id: UUID | None
    state: Literal["unmatched", "needs_review", "accepted", "rejected", "suppressed"]
    evidence_strength: Literal["explicit", "supported", "ambiguous", "none"]
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=40)
    rule_version: Literal["synthetic-association-v1"] = "synthetic-association-v1"
    reason: Literal[
        "explicit_observed_correspondence",
        "structural_hint",
        "ambiguous_identity",
        "no_author_mapping",
        "normalization_collision",
        "unsupported_address",
        "partial_document",
        "retained_locator_only",
        "reviewed_evidence",
        "reviewed_unlinked",
    ]
    heuristic_score: None = None
    calibrated_probability: None = None
    revision: int = Field(default=1, ge=1)


class Bundle(Record):
    schema_version: Literal["1.0"] = "1.0"
    organization_id: UUID
    article_id: UUID
    source_url: str = Field(min_length=1, max_length=2048)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1, max_length=64)
    observation_route: Literal["html", "browser_dom", "pdf", "article_xml"]
    observation_status: Literal[
        "observed", "no_contact", "requires_browser", "partial", "unsupported"
    ]
    preferred_metadata: MetadataValues
    authors: tuple[Author, ...] = Field(max_length=100)
    candidates: tuple[Candidate, ...] = Field(max_length=100)
    evidence: tuple[Evidence, ...] = Field(max_length=2400)
    associations: tuple[Association, ...] = Field(max_length=10000)
    technical_network_checks: Literal[False] = False
    exports_available: Literal[False] = False

    @field_validator("technical_network_checks", "exports_available", mode="before")
    @classmethod
    def unavailable_claims(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Unavailable capabilities require explicit boolean false")
        return value

    @model_validator(mode="after")
    def integrity(self) -> "Bundle":
        authors = {a.id: a for a in self.authors}
        candidates = {c.id: c for c in self.candidates}
        evidence = {e.id: e for e in self.evidence}
        if any(
            len(items) != len({i.id for i in items})
            for items in (self.authors, self.candidates, self.evidence, self.associations)
        ):
            raise ValueError("Distinct article-local records required")
        if [a.position for a in self.authors] != list(range(1, len(self.authors) + 1)):
            raise ValueError("Ordered observed authors required")
        for author in self.authors:
            if (
                author.first != (author.position == 1)
                or not set(author.evidence_ids) <= evidence.keys()
            ):
                raise ValueError("Role/evidence references require observed authors")
        for candidate in self.candidates:
            if (
                candidate.address.raw_address not in candidate.raw_variants
                or len(set(candidate.raw_variants)) != len(candidate.raw_variants)
                or candidate.address != normalize(candidate.address.raw_address)
                or any(
                    normalize(v).comparison_key != candidate.address.comparison_key
                    for v in candidate.raw_variants
                )
                or candidate.normalization_collision != (len(candidate.raw_variants) > 1)
                or not set(candidate.evidence_ids) <= evidence.keys()
            ):
                raise ValueError("Observed raw candidate provenance required")
        for association in self.associations:
            if (
                association.candidate_id not in candidates
                or (association.author_id is not None and association.author_id not in authors)
                or not set(association.evidence_ids) <= evidence.keys()
            ):
                raise ValueError("Tenant/article association references required")
            if association.state == "accepted":
                candidate = candidates[association.candidate_id]
                if (
                    association.author_id is None
                    or candidate.address.syntax_status != "valid"
                    or candidate.normalization_collision
                    or association.evidence_strength not in ("explicit", "supported")
                    or not set(candidate.evidence_ids) & set(association.evidence_ids)
                    or not set(authors[association.author_id].evidence_ids)
                    & set(association.evidence_ids)
                    or not all(evidence[i].excerpt for i in association.evidence_ids)
                ):
                    raise ValueError("Accepted mapping requires retained author/address evidence")
        return self


class Review(Record):
    association_id: UUID
    expected_revision: int = Field(ge=1)
    action: Literal["accept", "reject", "correct", "unlink"]
    author_id: UUID | None = None
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=300, pattern=r"\S")
