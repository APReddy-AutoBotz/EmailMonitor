"""Typed retained XML facts, distinct from the excerpt-required raw parser output."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from emailmonitor.extraction.html import AuthorFact, CandidateFact, Evidence, Fact, MetadataValues
from emailmonitor.extraction.sciencedirect import Reason, XmlObservation
from emailmonitor.sources.sciencedirect import API_ORIGIN, ArticleIdentifier, article_path

XML_URL = "https://synthetic.publisher.example/article-xml.xml"
XML_IDENTIFIER = ArticleIdentifier(kind="doi", value="10.9999/synthetic.1")
XML_PROFILE = "article_retrieval_response"
XML_DIGEST = "ecffa55455f07f6205a1bb2ab6bc30f7e2528845eae757a17c32d88c5fa4ec30"
MAX_ENVELOPE = 131072


class XmlBinding(Fact):
    organization: UUID
    job: UUID
    item: UUID
    generation: int = Field(ge=1)
    deletion_generation: int = Field(ge=1)
    policy_version: int = Field(ge=1)
    discovery_revision: int = Field(ge=1)


class RetainedXmlCandidate(CandidateFact):
    association_evidence: list[Evidence] = Field(default_factory=list, max_length=100)


class RetainedXml(Fact):
    schema_version: Literal["1.0"] = "1.0"
    parser_version: Literal["elsevier-xml-head-v1"] = "elsevier-xml-head-v1"
    route: Literal["article_xml"] = "article_xml"
    url: Literal["https://synthetic.publisher.example/article-xml.xml"] = (
        "https://synthetic.publisher.example/article-xml.xml"
    )
    canonical_url: str = Field(max_length=2048)
    requested_identifier: ArticleIdentifier
    source_profile: Literal["article_retrieval_response"] = "article_retrieval_response"
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "partial", "unsupported"]
    reasons: list[Reason] = Field(default_factory=list, max_length=20)
    authors: list[AuthorFact] = Field(default_factory=list, max_length=100)
    candidates: list[RetainedXmlCandidate] = Field(default_factory=list, max_length=100)
    preferred_metadata: MetadataValues = Field(default_factory=MetadataValues)
    binding: XmlBinding
    excerpts_retained: bool
    isolation_profile: Literal["network-none-parser-v1"] = "network-none-parser-v1"
    identity_association_implemented: Literal[False] = False

    @model_validator(mode="after")
    def retained_integrity(self) -> "RetainedXml":
        if (
            self.requested_identifier != XML_IDENTIFIER
            or self.canonical_url != API_ORIGIN + article_path(XML_IDENTIFIER)
            or self.content_digest != XML_DIGEST
            or self.acquisition_digest != XML_DIGEST
            or self.preferred_metadata != MetadataValues()
        ):
            raise ValueError("Fixed synthetic XML provenance required")
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
                or bool(candidate.author_positions) != bool(candidate.association_evidence)
                or bool(candidate.author_positions)
                != (candidate.association_status == "needs_review")
                or (
                    self.excerpts_retained
                    and candidate.raw_address not in candidate.evidence.excerpt
                )
            ):
                raise ValueError("Retained XML structural evidence required")
            evidence.extend([candidate.evidence, *candidate.association_evidence])
        if any(
            not e.locator.startswith("xml:/1")
            or e.kind != "structured_metadata"
            or bool(e.excerpt) != self.excerpts_retained
            for e in evidence
        ):
            raise ValueError("Consistent retained XML evidence required")
        if self.status == "unsupported":
            if not self.reasons or self.authors or self.candidates:
                raise ValueError("Unsupported outcome cannot assert facts")
        elif not self.authors:
            raise ValueError("Supported outcome requires authors")
        if self.status in ("observed", "no_contact") and (
            self.reasons or (self.status == "observed") != bool(self.candidates)
        ):
            raise ValueError("Complete outcome must agree with facts")
        if self.status == "partial" and not self.reasons:
            raise ValueError("Partial outcome needs reasons")
        return self


def retain_xml(observed: XmlObservation, binding: XmlBinding, excerpts: bool) -> RetainedXml:
    # Validate literal evidence before policy-driven stripping. Never attempt to
    # validate a locator-only retained record as raw XmlObservation.
    observed = XmlObservation.model_validate_json(observed.model_dump_json())
    document = observed.model_dump(mode="json")
    document.update(
        canonical_url=document.pop("url"),
        url=XML_URL,
        acquisition_digest=observed.content_digest,
        binding=binding.model_dump(mode="json"),
        excerpts_retained=excerpts and bool(observed.authors or observed.candidates),
    )

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
        strip(document)
    import json

    result = RetainedXml.model_validate_json(json.dumps(document))
    if len(result.model_dump_json().encode()) > MAX_ENVELOPE:
        raise ValueError("Retained XML envelope exceeds bounded ceiling")
    return result
