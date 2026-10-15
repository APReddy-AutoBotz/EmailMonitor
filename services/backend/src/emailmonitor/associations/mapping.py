"""Pure fixture-only deterministic rules; equal names never become person IDs."""

import json
from collections import defaultdict
from uuid import UUID, uuid5

from emailmonitor.associations.models import Association, Author, Bundle, Candidate, Evidence
from emailmonitor.associations.normalization import normalize
from emailmonitor.config import Settings
from emailmonitor.extraction.html import ArticleObservation, CandidateFact
from emailmonitor.extraction.pdf import PdfCandidate, PdfObservation
from emailmonitor.extraction.xml_retained import RetainedXml, RetainedXmlCandidate
from emailmonitor.fetching.fixture import require_fixture

NAMESPACE = UUID("a42e0727-8da5-4214-b8c3-ff41a8246800")


def identifier(org: UUID, kind: str, *parts: object) -> UUID:
    return uuid5(NAMESPACE, json.dumps([str(org), kind, *parts], ensure_ascii=True, sort_keys=True))


def map_observation(
    settings: Settings, org: UUID, value: ArticleObservation | PdfObservation | RetainedXml
) -> Bundle:
    require_fixture(settings)
    if type(org) is not UUID or value.content_digest is None:
        raise ValueError("Tenant context and bounded observed content digest required")
    # Revalidate the trusted-worker model: construction/copy are not proof.
    value = type(value).model_validate_json(value.model_dump_json())
    if value.content_digest is None:
        raise ValueError("Observed content digest required")
    source_candidates: list[CandidateFact | PdfCandidate] = [*value.candidates]
    source_url = value.url
    article = identifier(org, "article", source_url)
    prefix = (value.url, value.content_digest, value.parser_version)
    evidence: dict[UUID, Evidence] = {}

    def retain(fact: object) -> UUID:
        from emailmonitor.extraction.html import Evidence as HtmlEvidence
        from emailmonitor.extraction.pdf import PdfEvidence

        if not isinstance(fact, (HtmlEvidence, PdfEvidence)):
            raise ValueError("Observed parser evidence required")
        identity = identifier(org, "evidence", *prefix, fact.model_dump(mode="json"))
        evidence[identity] = Evidence(
            id=identity,
            locator=fact.locator,
            excerpt=fact.excerpt,
            method=fact.kind if isinstance(fact, HtmlEvidence) else "pdf_text",
            page=fact.page if isinstance(fact, PdfEvidence) else None,
            anchor=fact.anchor if isinstance(fact, PdfEvidence) else None,
            region=fact.region if isinstance(fact, PdfEvidence) else None,
            coordinate_units=fact.coordinate_units if isinstance(fact, PdfEvidence) else None,
            coordinate_origin=fact.coordinate_origin if isinstance(fact, PdfEvidence) else None,
            region_precision=fact.region_precision if isinstance(fact, PdfEvidence) else None,
        )
        return identity

    authors = tuple(
        Author(
            id=identifier(org, "author-instance", *prefix, a.position),
            position=a.position,
            display_name=a.display_name,
            first=a.first,
            corresponding=a.corresponding,
            kind=a.author_kind if hasattr(a, "author_kind") else "unknown",
            orcid=a.orcid if hasattr(a, "orcid") else None,
            affiliations=tuple(a.affiliations),
            evidence_ids=tuple(dict.fromkeys(retain(e) for e in a.evidence)),
        )
        for a in value.authors
    )
    by_position = {a.position: a for a in authors}
    groups: dict[str, list[int]] = defaultdict(list)
    for index, fact in enumerate(source_candidates):
        if (
            isinstance(fact, CandidateFact)
            and fact.evidence.excerpt
            and fact.raw_address not in fact.evidence.excerpt
        ):
            raise ValueError("Observed address must be retained literally in its evidence")
        groups[normalize(fact.raw_address).comparison_key].append(index)
    candidates: list[Candidate] = []
    associations: list[Association] = []
    for key, indices in groups.items():
        first = source_candidates[indices[0]]
        variants = tuple(dict.fromkeys(source_candidates[i].raw_address for i in indices))
        retained: list[UUID] = []
        positions: set[int] = set()
        for index in indices:
            fact = source_candidates[index]
            facts = fact.evidence if isinstance(fact.evidence, list) else [fact.evidence]
            retained.extend(retain(e) for e in facts)
            if isinstance(fact, RetainedXmlCandidate):
                retained.extend(retain(e) for e in fact.association_evidence)
            positions.update(fact.author_positions)
        candidate = Candidate(
            id=identifier(org, "candidate", key),
            address=normalize(first.raw_address),
            raw_variants=variants,
            normalization_collision=len(variants) > 1,
            evidence_ids=tuple(dict.fromkeys(retained)),
        )
        candidates.append(candidate)
        for position in sorted(positions) if positions else [None]:
            author = by_position[position] if position is not None else None
            ids = tuple(
                dict.fromkeys((*candidate.evidence_ids, *(author.evidence_ids if author else ())))
            )
            reason = "no_author_mapping" if author is None else "structural_hint"
            strength = "none" if author is None else "ambiguous"
            state = "unmatched" if author is None else "needs_review"
            duplicates = (
                author is not None
                and sum(
                    a.display_name.casefold() == author.display_name.casefold() for a in authors
                )
                > 1
            )
            retained_text = all(evidence[i].excerpt for i in ids)
            # Explicit correspondence needs source-role evidence and a unique hint;
            # name/local-part proximity is never an acceptance rule.
            explicit = (
                author is not None
                and author.corresponding is True
                and len(positions) == 1
                and not duplicates
                and any(
                    author.display_name in evidence[i].excerpt
                    and (
                        any(raw in evidence[i].excerpt for raw in variants)
                        or (
                            isinstance(value, PdfObservation)
                            and "Correspondence" in evidence[i].excerpt
                        )
                    )
                    for i in author.evidence_ids
                )
            )
            if candidate.address.syntax_status != "valid":
                reason = "unsupported_address"
            elif candidate.normalization_collision:
                reason = "normalization_collision"
            elif duplicates or len(positions) > 1:
                reason = "ambiguous_identity"
            elif value.status == "partial":
                reason = "partial_document"
            elif not retained_text:
                reason = "retained_locator_only"
            elif explicit and not isinstance(value, RetainedXml):
                state, strength, reason = "accepted", "explicit", "explicit_observed_correspondence"
            associations.append(
                Association.model_validate(
                    {
                        "id": identifier(org, "association", *prefix, str(candidate.id), position),
                        "candidate_id": candidate.id,
                        "author_id": author.id if author else None,
                        "state": state,
                        "evidence_strength": strength,
                        "evidence_ids": ids,
                        "reason": reason,
                    }
                )
            )
    return Bundle(
        organization_id=org,
        article_id=article,
        source_url=source_url,
        content_digest=value.content_digest,
        parser_version=value.parser_version,
        observation_route=value.route,
        observation_status=value.status,
        preferred_metadata=value.preferred_metadata,
        authors=authors,
        candidates=tuple(candidates),
        evidence=tuple(evidence.values()),
        associations=tuple(associations),
    )
