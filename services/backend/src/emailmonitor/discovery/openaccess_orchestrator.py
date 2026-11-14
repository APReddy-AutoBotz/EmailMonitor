"""Unified Open Access discovery orchestrator (offline gateways only).

Pipeline per query::

    route -> bounded work discovery (Europe PMC / OpenAlex / Crossref / bioRxiv)
          -> per-work identifier resolution (PMCID, or preprint DOI)
          -> that work's own full-text JATS XML
          -> literal address observations with evidence
          -> role filter, suppression, export readiness

Integrity rules (AGENTS.md product invariants):

* A contact is produced only from the full text of the article it is
  attributed to. A work whose own full text is unavailable is reported as a
  metadata-only outcome with zero contacts; it is never paired with another
  article's authors or addresses.
* Unknown metadata stays unknown (``None``). No DOI, year, journal or ORCID is
  defaulted. An ORCID is kept only when the article itself declares it on that
  author and its ISO 7064 check digit is valid.
* First author, corresponding author, extracted address, author association
  basis, technical check and export readiness are separate fields.
* Recency is a heuristic ordering weight, not a probability; syntax and domain
  checks do not prove a live mailbox.
* Gateways are injected. The defaults are committed offline fixtures; no live
  network path exists in this module.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.extraction.jats import JatsObservation, parse_jats_xml
from emailmonitor.extraction.orcid import validate_orcid_id
from emailmonitor.fetching.europepmc import EuropePmcFixtureGateway, EuropePmcRequest
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.results.outreach import (
    ContactExportItem,
    current_year,
    evaluate_contact,
    generate_gdpr_provenance,
    is_role_account,
    render_instantly_csv,
    render_smartlead_csv,
    split_author_name,
)
from emailmonitor.sources.biorxiv import (
    BioRxivFixtureGateway,
    BioRxivJatsFixtureGateway,
    BioRxivPreprint,
    BioRxivQueryPlanner,
    matches_keywords,
)
from emailmonitor.sources.crossref import (
    CrossrefFixtureGateway,
    CrossrefQueryPlanner,
    CrossrefWork,
)
from emailmonitor.sources.europepmc_search import (
    EuropePmcHit,
    EuropePmcSearchFixtureGateway,
    EuropePmcSearchPage,
    EuropePmcSearchRequest,
)
from emailmonitor.sources.openaccess import (
    DOI_PATTERN,
    DoiIdentifier,
    LicenseCategory,
    PmcIdentifier,
    license_category,
)
from emailmonitor.sources.openalex import (
    OpenAlexFilter,
    OpenAlexSearchRequest,
    OpenAlexWork,
    parse_openalex_search_response,
)

SourceName = Literal["europe-pmc", "openalex", "crossref", "biorxiv"]
ContactSource = Literal["europe-pmc", "openalex", "crossref", "biorxiv", "document"]
RequestedSource = Literal["europe-pmc", "openalex", "crossref", "biorxiv", "auto", "all"]
MULTI_SOURCES: tuple[SourceName, ...] = ("europe-pmc", "openalex", "crossref")
TargetRoles = Literal["corresponding", "first", "both", "all"]
OutcomeStatus = Literal[
    "contacts_observed",
    "no_contact",
    "full_text_unavailable",
    "excluded_by_filter",
    "failed",
]
MAX_RESULTS = 100
_PMCID = re.compile(r"^PMC\d{3,12}$", re.IGNORECASE)


class OpenAlexFixtureGateway:
    """Offline gateway serving committed OpenAlex work fixtures."""

    def __init__(self, fixture_path: object | None = None) -> None:
        from pathlib import Path

        self._path = (
            Path(str(fixture_path))
            if fixture_path
            else (
                Path(__file__).resolve().parents[5] / "fixtures" / "openalex" / "search-crispr.json"
            )
        )

    def search_works(self, request: OpenAlexSearchRequest) -> list[OpenAlexWork]:
        if not self._path.is_file():
            raise FetchDenied("missing_openalex_fixture")
        works = parse_openalex_search_response(self._path.read_bytes())
        return works[: request.per_page]


class EuropePmcFullText(Protocol):
    def fetch(self, request: EuropePmcRequest) -> object: ...


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryFilters(Contract):
    """Pre-extraction work filters. Excluded works are reported, not silently dropped."""

    from_year: int | None = Field(default=None, ge=1800, le=2100)
    until_year: int | None = Field(default=None, ge=1800, le=2100)
    exclude_journals: tuple[str, ...] = Field(default_factory=tuple, max_length=50)


class ArticleOutcome(Contract):
    """What happened to one discovered work. Counts are truthful, not inferred."""

    source: SourceName
    work_key: str = Field(max_length=300)
    doi: str | None = None
    pmcid: str | None = None
    title: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    status: OutcomeStatus
    reason: str | None = Field(default=None, max_length=200)
    full_text_url: str | None = None
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_url: str | None = None
    license_category: LicenseCategory = "unknown"
    found_in: tuple[SourceName, ...] = Field(default_factory=tuple)
    keywords: tuple[str, ...] = Field(default_factory=tuple)
    authors_observed: int = Field(default=0, ge=0)
    candidates_observed: int = Field(default=0, ge=0)
    unmatched_candidates: int = Field(default=0, ge=0)
    contacts_retained: int = Field(default=0, ge=0)


class ExtractedAcademicContact(Contract):
    """One literal address observation from one article, with provenance."""

    contact_id: str = Field(pattern=r"^oa-[0-9a-f]{20}$")
    source: ContactSource
    doi: str | None = None
    pmcid: str | None = None
    article_title: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    author_position: int | None = Field(default=None, ge=1, le=100)
    author_name: str | None = None
    author_kind: Literal["person", "group", "unknown"] = "unknown"
    first_name: str = ""
    last_name: str = ""
    email: str
    comparison_key: str
    is_first_author: bool
    is_corresponding_author: bool
    association_basis: str
    association_status: Literal["needs_review", "unmatched"]
    affiliations: tuple[str, ...] = Field(default_factory=tuple)
    orcid_id: str | None = None
    orcid_status: Literal["absent", "declared_valid_checksum", "declared_invalid_checksum"]
    evidence_locator: str
    evidence_excerpt: str
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_text_url: str | None = None
    domain_type: Literal["institutional", "commercial_free", "disposable"]
    recency_level: Literal["active_recent", "moderate", "dormant", "unknown"]
    recency_score: float = Field(ge=0.0, le=1.0)
    technical_status: Literal["syntax_valid_not_mailbox_verified", "syntax_invalid"]
    outreach_eligibility: Literal["eligible", "needs_review", "suppressed"]
    eligibility_reasons: tuple[str, ...] = Field(default_factory=tuple)
    gdpr_notice: str

    def to_export_item(self) -> ContactExportItem:
        role: Literal["corresponding", "first", "senior", "contributor"]
        if self.is_corresponding_author:
            role = "corresponding"
        elif self.is_first_author:
            role = "first"
        else:
            role = "contributor"
        return ContactExportItem(
            raw_email=self.email,
            display_name=self.author_name,
            orcid=self.orcid_id,
            affiliation=self.affiliations[0] if self.affiliations else None,
            role=role,
            paper_title=self.article_title or "",
            journal=self.journal,
            publication_year=self.publication_year,
            doi=self.doi,
            content_digest=self.content_digest,
        )


class DiscoveryResult(Contract):
    query: str
    source_used: SourceName | Literal["all"]
    route_reason: str
    target_roles: TargetRoles
    reference_year: int
    total_articles_scanned: int = Field(ge=0)
    articles_with_full_text: int = Field(ge=0)
    articles: tuple[ArticleOutcome, ...] = Field(default_factory=tuple)
    contacts_extracted: tuple[ExtractedAcademicContact, ...] = Field(default_factory=tuple)
    corresponding_authors_count: int = Field(ge=0)
    first_authors_count: int = Field(ge=0)
    unmatched_candidates_count: int = Field(ge=0)
    eligible_contacts_count: int = Field(ge=0)
    hit_count_reported: int | None = Field(default=None, ge=0)
    source_errors: dict[str, str] = Field(default_factory=dict)

    def eligible_items(self) -> list[ContactExportItem]:
        return [
            c.to_export_item()
            for c in self.contacts_extracted
            if c.outreach_eligibility == "eligible"
        ]

    def export_instantly_csv(self) -> bytes:
        return render_instantly_csv(self.eligible_items(), reference_year=self.reference_year)

    def export_smartlead_csv(self) -> bytes:
        return render_smartlead_csv(self.eligible_items(), reference_year=self.reference_year)


@dataclass(frozen=True)
class _Work:
    source: SourceName
    work_key: str
    doi: str | None
    pmcid: str | None
    title: str | None
    journal: str | None
    publication_year: int | None
    preprint_doi: DoiIdentifier | None = None
    preprint_url: str | None = None
    found_in: tuple[SourceName, ...] = ()


def normalize_doi(value: str) -> str | None:
    cleaned = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    return cleaned if DOI_PATTERN.match(cleaned) else None


def route_query(query: str) -> tuple[SourceName, str]:
    """Choose a source for ``auto``; the reason is reported with the result."""
    stripped = query.strip()
    if _PMCID.match(stripped):
        return "europe-pmc", "pmcid_identifier"
    doi = normalize_doi(stripped)
    if doi is not None:
        if doi.startswith("10.1101/"):
            return "biorxiv", "preprint_doi_prefix"
        return "crossref", "doi_identifier"
    return "europe-pmc", "keyword_full_text_search"


def _domain_suppressed(domain: str, suppressed_domains: frozenset[str]) -> bool:
    labels = domain.split(".")
    return any(".".join(labels[i:]) in suppressed_domains for i in range(len(labels)))


def contact_id_for(source: str, article_key: str, comparison_key: str) -> str:
    digest = hashlib.sha256(f"{source}\x1f{article_key}\x1f{comparison_key}".encode()).hexdigest()
    return f"oa-{digest[:20]}"


@dataclass(frozen=True)
class ArticleContext:
    """Article-level provenance shared by every contact observed in one document."""

    source: ContactSource
    article_key: str
    doi: str | None
    pmcid: str | None
    title: str | None
    journal: str | None
    publication_year: int | None
    content_digest: str
    full_text_url: str | None


@dataclass(frozen=True)
class AuthorView:
    position: int | None
    display_name: str
    kind: Literal["person", "group", "unknown"]
    first: bool
    corresponding: bool
    affiliations: tuple[str, ...] = ()
    orcid: str | None = None


def passes_role_filter(target_roles: TargetRoles, is_first: bool, is_corresp: bool) -> bool:
    if target_roles == "corresponding":
        return is_corresp
    if target_roles == "first":
        return is_first
    if target_roles == "both":
        return is_first or is_corresp
    return True


def build_contact(
    context: ArticleContext,
    *,
    address: str,
    author: AuthorView | None,
    association_basis: str,
    association_status: Literal["needs_review", "unmatched"],
    evidence_locator: str,
    evidence_excerpt: str,
    target_roles: TargetRoles,
    reference_year: int,
    suppressed_emails: frozenset[str],
    suppressed_domains: frozenset[str],
) -> ExtractedAcademicContact | None:
    """One observed address -> contact record, or None when the role filter excludes it."""
    is_first = bool(author and author.first)
    is_corresp = bool(author and author.corresponding)
    if not passes_role_filter(target_roles, is_first, is_corresp):
        return None

    comparison_key = address.casefold()
    domain = comparison_key.rsplit("@", 1)[-1]
    first_name, last_name = ("", "")
    if author and author.kind == "person":
        first_name, last_name = split_author_name(author.display_name)

    orcid_id: str | None = None
    orcid_status: Literal["absent", "declared_valid_checksum", "declared_invalid_checksum"] = (
        "absent"
    )
    if author and author.orcid:
        if validate_orcid_id(author.orcid):
            orcid_id, orcid_status = author.orcid, "declared_valid_checksum"
        else:
            orcid_status = "declared_invalid_checksum"

    item = ContactExportItem(
        raw_email=address,
        display_name=author.display_name if author else None,
        orcid=orcid_id,
        affiliation=author.affiliations[0] if author and author.affiliations else None,
        role="corresponding" if is_corresp else ("first" if is_first else "contributor"),
        paper_title=context.title or "",
        journal=context.journal,
        publication_year=context.publication_year,
        doi=context.doi,
        content_digest=context.content_digest,
    )
    score = evaluate_contact(item, reference_year)

    reasons: list[str] = []
    eligibility: Literal["eligible", "needs_review", "suppressed"] = "eligible"
    if comparison_key in suppressed_emails:
        eligibility, reasons = "suppressed", ["suppressed_address"]
    elif _domain_suppressed(domain, suppressed_domains):
        eligibility, reasons = "suppressed", ["suppressed_domain"]
    else:
        if not score.is_valid_syntax:
            reasons.append("invalid_syntax")
        if score.domain_type == "disposable":
            reasons.append("disposable_domain")
        if author is None:
            reasons.append("author_association_unresolved")
        elif author.kind != "person":
            reasons.append("group_author_address")
        if is_role_account(address):
            reasons.append("role_account")
        if reasons:
            eligibility = "needs_review"
        if score.domain_type == "commercial_free":
            reasons.append("free_mail_domain")
        if score.recency_level == "unknown":
            reasons.append("publication_year_unknown")

    return ExtractedAcademicContact(
        contact_id=contact_id_for(context.source, context.article_key, comparison_key),
        source=context.source,
        doi=context.doi,
        pmcid=context.pmcid,
        article_title=context.title,
        journal=context.journal,
        publication_year=context.publication_year,
        author_position=author.position if author else None,
        author_name=author.display_name if author else None,
        author_kind=author.kind if author else "unknown",
        first_name=first_name,
        last_name=last_name,
        email=address,
        comparison_key=comparison_key,
        is_first_author=is_first,
        is_corresponding_author=is_corresp,
        association_basis=association_basis,
        association_status=association_status,
        affiliations=author.affiliations if author else (),
        orcid_id=orcid_id,
        orcid_status=orcid_status,
        evidence_locator=evidence_locator,
        evidence_excerpt=evidence_excerpt,
        content_digest=context.content_digest,
        full_text_url=context.full_text_url,
        domain_type=score.domain_type,
        recency_level=score.recency_level,
        recency_score=score.recency_score,
        technical_status=(
            "syntax_valid_not_mailbox_verified" if score.is_valid_syntax else "syntax_invalid"
        ),
        outreach_eligibility=eligibility,
        eligibility_reasons=tuple(reasons),
        gdpr_notice=generate_gdpr_provenance(item),
    )


class OpenAccessOrchestrator:
    """Coordinates bounded discovery, own-article full text and contact extraction."""

    def __init__(
        self,
        europe_pmc_gateway: EuropePmcFixtureGateway | None = None,
        openalex_gateway: OpenAlexFixtureGateway | None = None,
        crossref_gateway: CrossrefFixtureGateway | None = None,
        biorxiv_gateway: BioRxivFixtureGateway | None = None,
        europe_pmc_search_gateway: EuropePmcSearchFixtureGateway | None = None,
        biorxiv_jats_gateway: BioRxivJatsFixtureGateway | None = None,
        reference_year: int | None = None,
    ) -> None:
        self._pmc = europe_pmc_gateway or EuropePmcFixtureGateway()
        self._openalex = openalex_gateway or OpenAlexFixtureGateway()
        self._crossref = crossref_gateway or CrossrefFixtureGateway()
        self._biorxiv = biorxiv_gateway or BioRxivFixtureGateway()
        self._search = europe_pmc_search_gateway or EuropePmcSearchFixtureGateway()
        self._biorxiv_jats = biorxiv_jats_gateway or BioRxivJatsFixtureGateway()
        self._reference_year = reference_year or current_year()

    # ------------------------------------------------------------------ public

    def discover_and_extract(
        self,
        query: str,
        source: RequestedSource = "auto",
        max_results: int = 25,
        target_roles: TargetRoles = "both",
        filters: DiscoveryFilters | None = None,
        suppressed_emails: Iterable[str] = (),
        suppressed_domains: Iterable[str] = (),
    ) -> DiscoveryResult:
        query = query.strip()
        if not query or len(query) > 1000 or any(ord(c) < 32 for c in query):
            raise FetchDenied("invalid_query")
        if not 1 <= max_results <= MAX_RESULTS:
            raise FetchDenied("max_results_out_of_bounds")
        filters = filters or DiscoveryFilters()
        effective: SourceName | Literal["all"]
        source_errors: dict[str, str] = {}
        hit_count: int | None
        if source == "all":
            effective, reason = "all", "merged_sources"
            works, source_errors = self._discover_all(query, max_results, filters)
            hit_count = None
        else:
            if source == "auto":
                effective, reason = route_query(query)
            else:
                effective, reason = source, "explicit_source"
            works, hit_count = self._discover(effective, query, max_results, filters)
        suppressed_e = frozenset(e.strip().casefold() for e in suppressed_emails if e.strip())
        suppressed_d = frozenset(
            d.strip().lower().lstrip("@").lstrip(".") for d in suppressed_domains if d.strip()
        )

        outcomes: list[ArticleOutcome] = []
        contacts: list[ExtractedAcademicContact] = []
        seen: set[tuple[str, str]] = set()
        for work in works[:max_results]:
            excluded = self._filter_reason(work, filters)
            if excluded:
                outcomes.append(self._outcome(work, "excluded_by_filter", excluded))
                continue
            outcome, found = self._process(work, target_roles, suppressed_e, suppressed_d)
            kept: list[ExtractedAcademicContact] = []
            for contact in found:
                key = (contact.comparison_key, contact.doi or contact.pmcid or work.work_key)
                if key in seen:
                    continue
                seen.add(key)
                kept.append(contact)
            contacts.extend(kept)
            outcomes.append(outcome.model_copy(update={"contacts_retained": len(kept)}))

        return DiscoveryResult(
            query=query,
            source_used=effective,
            route_reason=reason,
            target_roles=target_roles,
            reference_year=self._reference_year,
            total_articles_scanned=len(outcomes),
            articles_with_full_text=sum(
                1 for o in outcomes if o.status in ("contacts_observed", "no_contact")
            ),
            articles=tuple(outcomes),
            contacts_extracted=tuple(contacts),
            corresponding_authors_count=sum(1 for c in contacts if c.is_corresponding_author),
            first_authors_count=sum(1 for c in contacts if c.is_first_author),
            unmatched_candidates_count=sum(o.unmatched_candidates for o in outcomes),
            eligible_contacts_count=sum(
                1 for c in contacts if c.outreach_eligibility == "eligible"
            ),
            hit_count_reported=hit_count,
            source_errors=source_errors,
        )

    # --------------------------------------------------------------- discovery

    def _discover(
        self, source: SourceName, query: str, limit: int, filters: DiscoveryFilters
    ) -> tuple[list[_Work], int | None]:
        if source == "europe-pmc":
            return self._discover_europe_pmc(query, limit, filters)
        if source == "openalex":
            return self._discover_openalex(query, limit, filters), None
        if source == "crossref":
            return self._discover_crossref(query, limit, filters), None
        return self._discover_biorxiv(query, limit, filters), None

    def _discover_all(
        self, query: str, limit: int, filters: DiscoveryFilters
    ) -> tuple[list[_Work], dict[str, str]]:
        """Union of sources, deduplicated by PMCID, then DOI. One work is read once.

        A failing source is reported in ``source_errors``; others still run.
        """
        merged: dict[str, _Work] = {}
        order: list[str] = []
        errors: dict[str, str] = {}
        for name in MULTI_SOURCES:
            try:
                found, _count = self._discover(name, query, limit, filters)
            except (FetchDenied, ValueError) as exc:
                errors[name] = (str(exc) if isinstance(exc, FetchDenied) else "invalid_request")[
                    :200
                ]
                continue
            for work in found:
                keys = [k for k in (work.pmcid, work.doi) if k]
                existing = next((merged[k] for k in keys if k in merged), None)
                if existing is None:
                    record = replace(work, found_in=(name,))
                    primary = keys[0] if keys else f"{name}:{work.work_key}"
                    order.append(primary)
                else:
                    record = replace(
                        existing,
                        pmcid=existing.pmcid or work.pmcid,
                        doi=existing.doi or work.doi,
                        title=existing.title or work.title,
                        journal=existing.journal or work.journal,
                        publication_year=existing.publication_year or work.publication_year,
                        found_in=existing.found_in
                        + ((name,) if name not in existing.found_in else ()),
                    )
                    primary = next(o for o in order if merged.get(o) is existing)
                for key in [primary, *keys]:
                    merged[key] = record
        unique: list[_Work] = []
        for primary in order:
            unique.append(merged[primary])
        return unique[:limit], errors

    def _discover_europe_pmc(
        self, query: str, limit: int, filters: DiscoveryFilters
    ) -> tuple[list[_Work], int | None]:
        if _PMCID.match(query):
            pmcid = query.upper()
            return [_Work("europe-pmc", pmcid, None, pmcid, None, None, None)], None
        page: EuropePmcSearchPage = self._search.search(
            EuropePmcSearchRequest(
                query=query,
                page_size=limit,
                from_year=filters.from_year,
                until_year=filters.until_year,
            )
        )
        return [self._work_from_hit(hit) for hit in page.hits], page.hit_count

    @staticmethod
    def _work_from_hit(hit: EuropePmcHit) -> _Work:
        return _Work(
            source="europe-pmc",
            work_key=hit.pmcid or hit.doi or f"{hit.source}:{hit.source_id}",
            doi=hit.doi,
            pmcid=hit.pmcid if hit.full_text_xml_available else None,
            title=hit.title,
            journal=hit.journal_title,
            publication_year=hit.publication_year,
        )

    def _resolve_pmcid(self, doi: str | None) -> str | None:
        if not doi:
            return None
        try:
            hit = self._search.resolve_doi(doi)
        except FetchDenied:
            return None
        if hit is None or not hit.full_text_xml_available:
            return None
        return hit.pmcid

    def _discover_openalex(self, query: str, limit: int, filters: DiscoveryFilters) -> list[_Work]:
        request = OpenAlexSearchRequest(
            query=query[:300],
            per_page=limit,
            filters=OpenAlexFilter(
                from_publication_date=f"{filters.from_year}-01-01" if filters.from_year else None,
                to_publication_date=f"{filters.until_year}-12-31" if filters.until_year else None,
            ),
        )
        works: list[_Work] = []
        for item in self._openalex.search_works(request):
            doi = normalize_doi(item.doi) if item.doi else None
            pmcid = item.pmcid or self._resolve_pmcid(doi)
            works.append(
                _Work(
                    source="openalex",
                    work_key=item.id.rstrip("/").split("/")[-1],
                    doi=doi,
                    pmcid=pmcid,
                    title=item.title,
                    journal=item.journal_title,
                    publication_year=item.publication_year,
                )
            )
        return works

    def _discover_crossref(self, query: str, limit: int, filters: DiscoveryFilters) -> list[_Work]:
        doi = normalize_doi(query)
        items: tuple[CrossrefWork, ...]
        if doi is not None:
            resolved = self._crossref.resolve_doi(doi)
            items = (resolved,) if resolved else ()
        else:
            items = self._crossref.search_works(
                CrossrefQueryPlanner(
                    query=query[:500],
                    rows=limit,
                    from_year=filters.from_year,
                    until_year=filters.until_year,
                )
            )
        return [
            _Work(
                source="crossref",
                work_key=item.doi.value,
                doi=item.doi.value,
                pmcid=self._resolve_pmcid(item.doi.value),
                title=item.title,
                journal=item.container_title,
                publication_year=item.publication_year,
            )
            for item in items
        ]

    def _discover_biorxiv(self, query: str, limit: int, filters: DiscoveryFilters) -> list[_Work]:
        doi = normalize_doi(query)
        preprints: tuple[BioRxivPreprint, ...]
        if doi is not None:
            found = self._biorxiv.resolve_doi(DoiIdentifier(value=doi))
            preprints = (found,) if found else ()
        else:
            from_year = filters.from_year or self._reference_year - 1
            until_year = filters.until_year or self._reference_year
            listing = self._biorxiv.search_preprints(
                BioRxivQueryPlanner(
                    server="biorxiv",
                    from_date=f"{from_year}-01-01",
                    to_date=f"{until_year}-12-31",
                    limit=100,
                )
            )
            preprints = tuple(p for p in listing if matches_keywords(p, query))[:limit]
        return [
            _Work(
                source="biorxiv",
                work_key=p.doi.value,
                doi=p.doi.value,
                pmcid=None,
                title=p.title,
                journal=f"{p.server} (preprint)",
                publication_year=p.publication_year,
                preprint_doi=p.doi,
                preprint_url=p.jats_xml_url,
            )
            for p in preprints
        ]

    # -------------------------------------------------------------- per work

    def _filter_reason(self, work: _Work, filters: DiscoveryFilters) -> str | None:
        year = work.publication_year
        if filters.from_year is not None and (year is None or year < filters.from_year):
            return "before_from_year" if year is not None else "year_unknown"
        if filters.until_year is not None and (year is None or year > filters.until_year):
            return "after_until_year" if year is not None else "year_unknown"
        if work.journal and any(
            j.strip().lower() and j.strip().lower() in work.journal.lower()
            for j in filters.exclude_journals
        ):
            return "journal_excluded"
        return None

    @staticmethod
    def _outcome(work: _Work, status: OutcomeStatus, reason: str | None) -> ArticleOutcome:
        return ArticleOutcome(
            source=work.source,
            work_key=work.work_key[:300],
            doi=work.doi,
            pmcid=work.pmcid,
            title=work.title,
            journal=work.journal,
            publication_year=work.publication_year,
            status=status,
            reason=reason,
            found_in=work.found_in or (work.source,),
        )

    def _full_text(self, work: _Work) -> tuple[JatsObservation, str]:
        if work.pmcid:
            identifier = PmcIdentifier(value=work.pmcid)
            request = EuropePmcRequest(pmcid=identifier)
            response = self._pmc.fetch(request)
            body: bytes = response.body
            obs = parse_jats_xml(body, identifier)
            if obs.article_pmcid and obs.article_pmcid != identifier.value:
                raise FetchDenied("full_text_identifier_mismatch")
            return obs, request.url
        if work.preprint_doi is not None:
            data = self._biorxiv_jats.fetch_jats(work.preprint_doi)
            obs = parse_jats_xml(data, work.preprint_doi)
            url = work.preprint_url or f"https://doi.org/{work.preprint_doi.value}"
            return obs, url
        raise FetchDenied("no_full_text_route")

    def _process(
        self,
        work: _Work,
        target_roles: TargetRoles,
        suppressed_emails: frozenset[str],
        suppressed_domains: frozenset[str],
    ) -> tuple[ArticleOutcome, list[ExtractedAcademicContact]]:
        try:
            obs, full_text_url = self._full_text(work)
        except FetchDenied as exc:
            reason = str(exc)
            unavailable = reason in (
                "no_full_text_route",
                "unregistered_pmc_fixture",
                "preprint_full_text_unavailable",
                "missing_fixture_file",
            )
            status: OutcomeStatus = "full_text_unavailable" if unavailable else "failed"
            return self._outcome(work, status, reason[:200]), []

        obs_doi = normalize_doi(obs.doi) if obs.doi else None
        if work.doi and obs_doi and obs_doi != work.doi:
            return self._outcome(work, "failed", "full_text_doi_mismatch"), []

        doi = work.doi or obs_doi
        title = obs.title or work.title
        journal = obs.journal or work.journal
        year = work.publication_year
        if obs.publication_date and re.match(r"^\d{4}", obs.publication_date):
            year = int(obs.publication_date[:4])

        by_position = {a.position: a for a in obs.authors}
        contacts: list[ExtractedAcademicContact] = []
        unmatched = 0
        context = ArticleContext(
            source=work.source,
            article_key=work.pmcid or doi or work.work_key,
            doi=doi,
            pmcid=work.pmcid,
            title=title,
            journal=journal,
            publication_year=year,
            content_digest=obs.content_digest,
            full_text_url=full_text_url,
        )
        for candidate in obs.candidates:
            if candidate.association_basis == "unmatched":
                unmatched += 1
            fact = (
                by_position.get(candidate.author_positions[0])
                if candidate.author_positions
                else None
            )
            author = (
                AuthorView(
                    position=fact.position,
                    display_name=fact.display_name,
                    kind=fact.author_kind,
                    first=fact.first,
                    corresponding=bool(fact.corresponding),
                    affiliations=tuple(fact.affiliations),
                    orcid=fact.orcid,
                )
                if fact
                else None
            )
            contact = build_contact(
                context,
                address=candidate.raw_address,
                author=author,
                association_basis=candidate.association_basis,
                association_status=candidate.association_status,
                evidence_locator=candidate.evidence.locator,
                evidence_excerpt=candidate.evidence.excerpt,
                target_roles=target_roles,
                reference_year=self._reference_year,
                suppressed_emails=suppressed_emails,
                suppressed_domains=suppressed_domains,
            )
            if contact is not None:
                contacts.append(contact)

        outcome = ArticleOutcome(
            source=work.source,
            work_key=work.work_key[:300],
            doi=doi,
            pmcid=work.pmcid,
            title=title,
            journal=journal,
            publication_year=year,
            status="contacts_observed" if obs.candidates else "no_contact",
            full_text_url=full_text_url,
            content_digest=obs.content_digest,
            license_url=obs.license_url,
            license_category=license_category(obs.license_url),
            found_in=work.found_in or (work.source,),
            keywords=tuple(obs.keywords),
            authors_observed=len(obs.authors),
            candidates_observed=len(obs.candidates),
            unmatched_candidates=unmatched,
        )
        return outcome, contacts
