"""Open Access export presets over extracted contact records (OA-019).

Every preset is a file the operator imports elsewhere; nothing is sent.
Formula safety follows ``results.render.safe_csv``: an unsafe cell is never
rewritten. Instead the whole row is withheld and counted, so one hostile or
unlucky value (a title beginning with ``-`` or ``@``) cannot block an export
or be silently altered.

Outreach presets include only ``eligible`` rows. The ``evidence`` preset is a
review/audit file: every non-suppressed row with its association basis,
evidence excerpt, document digest and eligibility reasons.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from emailmonitor.discovery.openaccess_orchestrator import (
    AssociationStrength,
    ExtractedAcademicContact,
    meets_strength,
)
from emailmonitor.results.outreach import split_author_name
from emailmonitor.results.render import RenderDenied, safe_csv

ExportPreset = Literal["instantly", "smartlead", "lemlist", "hubspot", "evidence"]
EXPORT_PRESETS: tuple[ExportPreset, ...] = (
    "instantly",
    "smartlead",
    "lemlist",
    "hubspot",
    "evidence",
)
MAX_EXPORT_BYTES = 50 * 1024 * 1024

Row = Callable[[ExtractedAcademicContact], list[str]]


@dataclass(frozen=True)
class ExportFile:
    preset: ExportPreset
    filename: str
    content: bytes
    rows_written: int
    rows_withheld_unsafe: int
    rows_excluded_not_eligible: int


def _year(c: ExtractedAcademicContact) -> str:
    return str(c.publication_year) if c.publication_year else ""


def _names(c: ExtractedAcademicContact) -> tuple[str, str]:
    if c.first_name or c.last_name:
        return c.first_name, c.last_name
    return split_author_name(c.author_name)


def _affiliation(c: ExtractedAcademicContact) -> str:
    return c.affiliations[0] if c.affiliations else ""


def _receipt(c: ExtractedAcademicContact) -> str:
    return c.gdpr_notice


def _instantly(c: ExtractedAcademicContact) -> list[str]:
    first, last = _names(c)
    return [
        c.email,
        first,
        last,
        _affiliation(c),
        f"Enjoyed your recent paper on {c.article_title}" if c.article_title else "",
        c.article_title or "",
        c.journal or "",
        _year(c),
        c.doi or "",
        _receipt(c),
    ]


def _smartlead(c: ExtractedAcademicContact) -> list[str]:
    first, last = _names(c)
    return [
        c.email,
        first,
        last,
        _affiliation(c),
        c.article_title or "",
        c.journal or "",
        _year(c),
        c.doi or "",
        f"{c.recency_score:.1f}",
        _receipt(c),
    ]


def _lemlist(c: ExtractedAcademicContact) -> list[str]:
    first, last = _names(c)
    return [
        c.email,
        first,
        last,
        _affiliation(c),
        c.article_title or "",
        c.journal or "",
        _year(c),
        f"https://doi.org/{c.doi}" if c.doi else "",
        _receipt(c),
    ]


def _hubspot(c: ExtractedAcademicContact) -> list[str]:
    first, last = _names(c)
    return [
        c.email,
        first,
        last,
        _affiliation(c),
        c.article_title or "",
        c.journal or "",
        _year(c),
        c.doi or "",
        c.orcid_id or "",
        "EmailMonitor Open Access extraction",
        _receipt(c),
    ]


def _evidence(c: ExtractedAcademicContact) -> list[str]:
    return [
        c.contact_id,
        c.email,
        c.author_name or "",
        str(c.author_position or ""),
        "yes" if c.is_first_author else "no",
        "yes" if c.is_corresponding_author else "no",
        c.association_basis,
        c.association_status,
        _affiliation(c),
        c.orcid_id or "",
        c.orcid_status,
        c.doi or "",
        c.pmcid or "",
        c.article_title or "",
        c.journal or "",
        _year(c),
        c.source,
        c.full_text_url or "",
        c.content_digest,
        c.evidence_locator,
        c.evidence_excerpt,
        c.technical_status,
        c.recency_level,
        c.outreach_eligibility,
        "; ".join(c.eligibility_reasons),
    ]


_PRESETS: dict[ExportPreset, tuple[list[str], Row, bool]] = {
    "instantly": (
        [
            "email",
            "first_name",
            "last_name",
            "company_name",
            "personalization",
            "custom_paper_title",
            "custom_journal",
            "custom_publication_year",
            "custom_doi",
            "custom_gdpr_receipt",
        ],
        _instantly,
        True,
    ),
    "smartlead": (
        [
            "Email",
            "First Name",
            "Last Name",
            "Company",
            "Custom_Paper_Title",
            "Custom_Journal",
            "Custom_Year",
            "Custom_DOI",
            "Custom_Recency_Score",
            "GDPR_Notice",
        ],
        _smartlead,
        True,
    ),
    "lemlist": (
        [
            "email",
            "firstName",
            "lastName",
            "companyName",
            "paperTitle",
            "journal",
            "publicationYear",
            "doiLink",
            "gdprNotice",
        ],
        _lemlist,
        True,
    ),
    "hubspot": (
        [
            "Email",
            "First Name",
            "Last Name",
            "Company Name",
            "Recent Paper Title",
            "Journal",
            "Publication Year",
            "DOI",
            "ORCID",
            "Lead Source Detail",
            "Legal Basis Note",
        ],
        _hubspot,
        True,
    ),
    "evidence": (
        [
            "contact_id",
            "email",
            "author_name",
            "author_position",
            "first_author",
            "corresponding_author",
            "association_basis",
            "association_status",
            "affiliation",
            "orcid",
            "orcid_status",
            "doi",
            "pmcid",
            "title",
            "journal",
            "publication_year",
            "source",
            "full_text_url",
            "content_sha256",
            "evidence_locator",
            "evidence_excerpt",
            "technical_status",
            "recency_level",
            "outreach_eligibility",
            "eligibility_reasons",
        ],
        _evidence,
        False,
    ),
}


def write_rows_withholding(
    header: Sequence[str], rows: Iterable[Sequence[str]]
) -> tuple[bytes, int, int]:
    """CSV with QUOTE_ALL; rows containing an unsafe cell are withheld, not altered."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([safe_csv(h) for h in header])
    written = withheld = 0
    for row in rows:
        try:
            cells = [safe_csv(value) for value in row]
        except RenderDenied:
            withheld += 1
            continue
        writer.writerow(cells)
        written += 1
        if buffer.tell() > MAX_EXPORT_BYTES:
            raise RenderDenied("render_limit")
    return buffer.getvalue().encode("utf-8"), written, withheld


def render_export(
    preset: ExportPreset,
    contacts: Iterable[ExtractedAcademicContact],
    minimum_strength: AssociationStrength = "labelled",
) -> ExportFile:
    if preset not in _PRESETS:
        raise ValueError("unknown_export_preset")
    header, row, eligible_only = _PRESETS[preset]
    selected: list[ExtractedAcademicContact] = []
    excluded = 0
    seen: set[str] = set()
    for contact in contacts:
        if contact.outreach_eligibility == "suppressed":
            excluded += 1
            continue
        if eligible_only and (
            contact.outreach_eligibility != "eligible"
            or not meets_strength(contact.association_strength, minimum_strength)
        ):
            excluded += 1
            continue
        # Outreach presets carry one row per address (latest-first input wins);
        # the evidence preset keeps every observation.
        if eligible_only:
            if contact.comparison_key in seen:
                continue
            seen.add(contact.comparison_key)
        selected.append(contact)
    content, written, withheld = write_rows_withholding(header, (row(c) for c in selected))
    return ExportFile(
        preset=preset,
        filename=f"emailmonitor-{preset}-export.csv",
        content=content,
        rows_written=written,
        rows_withheld_unsafe=withheld,
        rows_excluded_not_eligible=excluded,
    )
