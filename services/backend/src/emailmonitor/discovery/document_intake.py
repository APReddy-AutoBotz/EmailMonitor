"""Single-document intake: a user-supplied article PDF, JATS XML or landing page.

This is the "I already opened this article" workflow: an operator saves a
publisher page or downloads the article PDF they are permitted to read, and
submits the bytes. Nothing is fetched; links found in the document (e.g. a
``citation_pdf_url``) are reported, never followed. Output uses the same
contact record, eligibility and suppression rules as the API pipeline.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.discovery.openaccess_orchestrator import (
    ArticleContext,
    AuthorView,
    ExtractedAcademicContact,
    TargetRoles,
    build_contact,
    normalize_doi,
)
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.results.outreach import (
    current_year,
    render_instantly_csv,
    render_smartlead_csv,
)
from emailmonitor.sources.openaccess import (
    DoiIdentifier,
    OpenAccessIdentifier,
    PmcIdentifier,
    license_category,
)

DocumentKind = Literal["pdf", "jats_xml", "html"]
MAX_DOCUMENT_BYTES = 20_971_520
_ID_TYPE = re.compile(rb"pub-id-type\s*=\s*[\"']([a-z]{2,10})[\"']")
_PMC_DIGITS = re.compile(rb"(?:PMC)?(\d{3,10})")
MAX_ARTICLE_IDS = 50
SCAN_WINDOW = 262_144


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentExtractionResult(Contract):
    kind: DocumentKind
    parser_version: str
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str
    reason: str | None = None
    title: str | None = None
    journal: str | None = None
    doi: str | None = None
    publication_year: int | None = None
    authors: tuple[str, ...] = Field(default_factory=tuple)
    contacts: tuple[ExtractedAcademicContact, ...] = Field(default_factory=tuple)
    candidates_observed: int = Field(default=0, ge=0)
    unmatched_candidates: int = Field(default=0, ge=0)
    review_notes: tuple[str, ...] = Field(default_factory=tuple)
    linked_pdf_url: str | None = None
    reference_year: int

    def export_instantly_csv(self) -> bytes:
        items = [c.to_export_item() for c in self.contacts if c.outreach_eligibility == "eligible"]
        return render_instantly_csv(items, reference_year=self.reference_year)

    def export_smartlead_csv(self) -> bytes:
        items = [c.to_export_item() for c in self.contacts if c.outreach_eligibility == "eligible"]
        return render_smartlead_csv(items, reference_year=self.reference_year)


def sniff_document(data: bytes) -> DocumentKind:
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"%PDF-"):
        return "pdf"
    lowered = head.lower()
    if lowered.startswith(b"<?xml") or lowered.startswith(b"<!doctype article"):
        if b"<article" in data[:65536].lower():
            return "jats_xml"
    if lowered.startswith(b"<article") and b"<front" in data[:65536].lower():
        return "jats_xml"
    if b"<html" in lowered or b"<!doctype html" in lowered or b"<meta" in lowered:
        return "html"
    raise FetchDenied("unsupported_document_type")


def _year(value: str | None) -> int | None:
    if value and re.match(r"^(19|20)\d\d", value):
        return int(value[:4])
    return None


def _article_ids(data: bytes) -> list[tuple[bytes, bytes]]:
    """(pub-id-type, value) for the first ``<article-id>`` elements; linear, bounded.

    A pre-scan only to name the document; the full XML is parsed afterwards
    under the safe parser, which also verifies the identifiers it reports.
    """
    window = data[:SCAN_WINDOW]
    found: list[tuple[bytes, bytes]] = []
    position = window.find(b"<article-id")
    while position != -1 and len(found) < MAX_ARTICLE_IDS:
        close = window.find(b">", position, position + 300)
        if close == -1:
            position = window.find(b"<article-id", position + 11)
            continue
        end = window.find(b"<", close + 1, close + 1 + 300)
        kind = _ID_TYPE.search(window, position, close)
        if end != -1 and kind:
            found.append((kind.group(1).lower(), window[close + 1 : end].strip()))
        position = window.find(b"<article-id", close)
    return found


def _jats_identifier(data: bytes) -> OpenAccessIdentifier:
    ids = _article_ids(data)
    for kind, value in ids:
        if kind in (b"pmc", b"pmcid"):
            digits = _PMC_DIGITS.fullmatch(value.upper())
            if digits:
                return PmcIdentifier(value="PMC" + digits.group(1).decode())
    for kind, value in ids:
        if kind == b"doi":
            try:
                return DoiIdentifier(value=value.decode("utf-8", errors="strict"))
            except (ValueError, UnicodeDecodeError):
                continue
    raise FetchDenied("jats_identifier_missing")


def extract_document(
    data: bytes,
    *,
    page_url: str | None = None,
    known_authors: Sequence[str] = (),
    target_roles: TargetRoles = "all",
    suppressed_emails: Iterable[str] = (),
    suppressed_domains: Iterable[str] = (),
    reference_year: int | None = None,
) -> DocumentExtractionResult:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise FetchDenied("document_byte_limit_exceeded")
    if not data.strip():
        raise FetchDenied("empty_document")
    year_ref = reference_year or current_year()
    kind = sniff_document(data)
    digest = hashlib.sha256(data).hexdigest()
    sup_e = frozenset(e.strip().casefold() for e in suppressed_emails if e.strip())
    sup_d = frozenset(
        d.strip().lower().lstrip("@").lstrip(".") for d in suppressed_domains if d.strip()
    )

    def make(
        context: ArticleContext,
        address: str,
        author: AuthorView | None,
        basis: str,
        status: Literal["needs_review", "unmatched"],
        locator: str,
        excerpt: str,
    ) -> ExtractedAcademicContact | None:
        return build_contact(
            context,
            address=address,
            author=author,
            association_basis=basis,
            association_status=status,
            evidence_locator=locator,
            evidence_excerpt=excerpt,
            target_roles=target_roles,
            reference_year=year_ref,
            suppressed_emails=sup_e,
            suppressed_domains=sup_d,
        )

    contacts: list[ExtractedAcademicContact] = []

    if kind == "jats_xml":
        identifier = _jats_identifier(data)
        obs = parse_jats_xml(data, identifier)
        doi = normalize_doi(obs.doi) if obs.doi else None
        context = ArticleContext(
            source="document",
            article_key=digest,
            doi=doi,
            pmcid=obs.article_pmcid,
            title=obs.title,
            journal=obs.journal,
            publication_year=_year(obs.publication_date),
            content_digest=digest,
            full_text_url=page_url,
            license_category=license_category(obs.license_url),
        )
        by_position = {a.position: a for a in obs.authors}
        for candidate in obs.candidates:
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
            contact = make(
                context,
                candidate.raw_address,
                author,
                candidate.association_basis,
                candidate.association_status,
                candidate.evidence.locator,
                candidate.evidence.excerpt,
            )
            if contact:
                contacts.append(contact)
        return DocumentExtractionResult(
            kind=kind,
            parser_version=obs.parser_version,
            content_digest=digest,
            status=obs.status,
            title=obs.title,
            journal=obs.journal,
            doi=doi,
            publication_year=context.publication_year,
            authors=tuple(a.display_name for a in obs.authors),
            contacts=tuple(contacts),
            candidates_observed=len(obs.candidates),
            unmatched_candidates=sum(
                1 for c in obs.candidates if c.association_basis == "unmatched"
            ),
            reference_year=year_ref,
        )

    if kind == "html":
        page = parse_citation_page(data, page_url)
        context = ArticleContext(
            source="document",
            article_key=page.doi or digest,
            doi=page.doi,
            pmcid=None,
            title=page.title,
            journal=page.journal,
            publication_year=_year(page.publication_date),
            content_digest=digest,
            full_text_url=page_url,
        )
        page_positions = {a.position: a for a in page.authors}
        for page_candidate in page.candidates:
            page_author = (
                page_positions.get(page_candidate.author_positions[0])
                if page_candidate.author_positions
                else None
            )
            author = (
                AuthorView(
                    position=page_author.position,
                    display_name=page_author.display_name,
                    kind="person",
                    first=page_author.first,
                    corresponding=bool(page_author.corresponding),
                    affiliations=page_author.institutions,
                    orcid=page_author.orcid,
                )
                if page_author
                else None
            )
            contact = make(
                context,
                page_candidate.raw_address,
                author,
                page_candidate.association_basis,
                page_candidate.association_status,
                page_candidate.evidence.locator,
                page_candidate.evidence.excerpt,
            )
            if contact:
                contacts.append(contact)
        notes: list[str] = []
        if page.obfuscated_address_count:
            notes.append(
                f"{page.obfuscated_address_count} obfuscated address(es) present; not decoded"
            )
        if page.status == "no_contact" and page.pdf_url:
            notes.append("no address on the page; the article PDF may list correspondence")
        return DocumentExtractionResult(
            kind=kind,
            parser_version=page.parser_version,
            content_digest=digest,
            status=page.status,
            title=page.title,
            journal=page.journal,
            doi=page.doi,
            publication_year=context.publication_year,
            authors=tuple(a.display_name for a in page.authors),
            contacts=tuple(contacts),
            candidates_observed=len(page.candidates),
            unmatched_candidates=sum(
                1 for c in page.candidates if c.association_basis == "unmatched"
            ),
            review_notes=tuple(notes),
            linked_pdf_url=page.pdf_url,
            reference_year=year_ref,
        )

    pdf = parse_pdf_contacts(data, known_authors=known_authors)
    names = [a.strip()[:300] for a in known_authors[:100] if a.strip()]
    context = ArticleContext(
        source="document",
        article_key=pdf.doi or digest,
        doi=pdf.doi,
        pmcid=None,
        title=pdf.title,
        journal=None,
        publication_year=None,
        content_digest=digest,
        full_text_url=page_url,
    )
    for pdf_candidate in pdf.candidates:
        author = None
        if pdf_candidate.author_name is not None and pdf_candidate.author_position is not None:
            position = pdf_candidate.author_position
            author = AuthorView(
                position=position,
                display_name=pdf_candidate.author_name,
                kind="person",
                first=position == 1,
                # Only correspondence wording asserts the role; an "E-mail:" list does not.
                corresponding=pdf_candidate.association_basis == "pdf_correspondence_surname",
            )
        contact = make(
            context,
            pdf_candidate.raw_address,
            author,
            pdf_candidate.association_basis,
            pdf_candidate.association_status,
            f"page[{pdf_candidate.page}]/line[{pdf_candidate.line}]",
            pdf_candidate.excerpt,
        )
        if contact:
            contacts.append(contact)
    notes = []
    if not names:
        notes.append("no known author names supplied; PDF addresses stay unmatched")
    if pdf.grouped_address_notations:
        notes.append(f"{pdf.grouped_address_notations} grouped address notation(s) not expanded")
    if pdf.possibly_wrapped_addresses:
        notes.append(f"{pdf.possibly_wrapped_addresses} address(es) may wrap across lines")
    if pdf.truncated:
        notes.append("text limit reached; later text not inspected")
    return DocumentExtractionResult(
        kind=kind,
        parser_version=pdf.parser_version,
        content_digest=digest,
        status=pdf.status,
        reason=pdf.reason,
        title=pdf.title,
        doi=pdf.doi,
        authors=tuple(names),
        contacts=tuple(contacts),
        candidates_observed=len(pdf.candidates),
        unmatched_candidates=sum(1 for c in pdf.candidates if c.association_basis == "unmatched"),
        review_notes=tuple(notes),
        reference_year=year_ref,
    )
