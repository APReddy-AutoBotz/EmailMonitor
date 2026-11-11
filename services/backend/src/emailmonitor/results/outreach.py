"""Cold outreach export formatting, deliverability scoring, and GDPR provenance.

Generates 1-click import files for Instantly.ai, Smartlead.ai, and academic CRMs
with immutable GDPR Legitimate Interest receipts, recency scoring, and suppression filtering.
"""

import csv
import io
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from emailmonitor.results.render import safe_csv

DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "tempmail.com",
        "10minutemail.com",
        "guerrillamail.com",
        "yopmail.com",
        "trashmail.com",
        "dispostable.com",
    }
)

FREE_COMMERCIAL_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
    }
)

HONORIFICS = re.compile(
    r"^(?:Prof\.?|Dr\.?|Doctor|Professor|Assoc\.?\s+Prof\.?|Assist\.?\s+Prof\.?)\s+",
    re.IGNORECASE,
)
SUFFIXES = re.compile(
    r",?\s+(?:Ph\.?D\.?|M\.?D\.?|FACS|FRCP|M\.?Sc\.?|B\.?Sc\.?|Esq\.?)\.?$",
    re.IGNORECASE,
)
EMAIL_SYNTAX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ContactExportItem(Contract):
    raw_email: str
    display_name: str | None = None
    orcid: str | None = None
    affiliation: str | None = None
    role: Literal["corresponding", "first", "senior", "contributor"] = (
        "corresponding"
    )
    paper_title: str
    journal: str
    publication_year: int
    publication_date: str | None = None
    doi: str | None = None
    content_digest: str | None = None


@dataclass(frozen=True)
class ContactScore:
    is_valid_syntax: bool
    domain_type: Literal["institutional", "commercial_free", "disposable"]
    recency_level: Literal["active_recent", "moderate", "dormant"]
    recency_score: float
    outreach_eligible: bool
    rejection_reason: str | None = None


def split_author_name(full_name: str | None) -> tuple[str, str]:
    """Split display name into (first_name, last_name) stripping titles and degrees."""
    if not full_name or not full_name.strip():
        return "", ""
    cleaned = HONORIFICS.sub("", full_name.strip())
    cleaned = SUFFIXES.sub("", cleaned).strip()

    parts = cleaned.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def evaluate_contact(item: ContactExportItem, reference_year: int = 2026) -> ContactScore:
    """Assess email syntax, domain classification, and publication recency."""
    email = item.raw_email.strip().lower()
    if not EMAIL_SYNTAX.match(email):
        return ContactScore(
            is_valid_syntax=False,
            domain_type="disposable",
            recency_level="dormant",
            recency_score=0.0,
            outreach_eligible=False,
            rejection_reason="invalid_email_syntax",
        )

    domain = email.split("@", 1)[1]
    if domain in DISPOSABLE_DOMAINS:
        return ContactScore(
            is_valid_syntax=True,
            domain_type="disposable",
            recency_level="dormant",
            recency_score=0.0,
            outreach_eligible=False,
            rejection_reason="disposable_domain_prohibited",
        )

    if domain in FREE_COMMERCIAL_DOMAINS:
        domain_type: Literal["institutional", "commercial_free", "disposable"] = (
            "commercial_free"
        )
    else:
        domain_type = "institutional"

    age = max(0, reference_year - item.publication_year)
    if age <= 1:
        recency_level: Literal["active_recent", "moderate", "dormant"] = (
            "active_recent"
        )
        recency_score = 1.0
    elif age <= 3:
        recency_level = "moderate"
        recency_score = 0.8
    else:
        recency_level = "dormant"
        recency_score = 0.5

    return ContactScore(
        is_valid_syntax=True,
        domain_type=domain_type,
        recency_level=recency_level,
        recency_score=recency_score,
        outreach_eligible=True,
        rejection_reason=None,
    )


def generate_gdpr_provenance(item: ContactExportItem) -> str:
    """Generate immutable GDPR Article 6(1)(f) Legitimate Interest provenance."""
    doi_part = f", DOI: {item.doi}" if item.doi else ""
    return (
        f"Notice: Address observed in published work '{item.paper_title}', "
        f"published in {item.journal} ({item.publication_year}){doi_part}. "
        "Processed under GDPR Article 6(1)(f) Legitimate Interest."
    )


def render_instantly_csv(
    items: list[ContactExportItem],
    suppressed_emails: frozenset[str] | set[str] | None = None,
    reference_year: int = 2026,
) -> bytes:
    """Render export matching Instantly.ai lead import CSV format."""
    suppressed = (
        {s.lower().strip() for s in suppressed_emails}
        if suppressed_emails
        else set()
    )

    rows: list[list[str]] = [
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
        ]
    ]

    for item in items:
        clean_email = item.raw_email.strip().lower()
        if clean_email in suppressed:
            continue
        score = evaluate_contact(item, reference_year)
        if not score.outreach_eligible:
            continue

        first_name, last_name = split_author_name(item.display_name)
        personalization = (
            f"Enjoyed your recent paper on {item.paper_title}"
            if item.paper_title
            else ""
        )
        provenance = generate_gdpr_provenance(item)

        rows.append(
            [
                clean_email,
                first_name,
                last_name,
                item.affiliation or "",
                personalization,
                item.paper_title,
                item.journal,
                str(item.publication_year),
                item.doi or "",
                provenance,
            ]
        )

    return _write_safe_csv(rows)


def render_smartlead_csv(
    items: list[ContactExportItem],
    suppressed_emails: frozenset[str] | set[str] | None = None,
    reference_year: int = 2026,
) -> bytes:
    """Render export matching Smartlead.ai lead import CSV format."""
    suppressed = (
        {s.lower().strip() for s in suppressed_emails}
        if suppressed_emails
        else set()
    )

    rows: list[list[str]] = [
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
        ]
    ]

    for item in items:
        clean_email = item.raw_email.strip().lower()
        if clean_email in suppressed:
            continue
        score = evaluate_contact(item, reference_year)
        if not score.outreach_eligible:
            continue

        first_name, last_name = split_author_name(item.display_name)
        provenance = generate_gdpr_provenance(item)

        rows.append(
            [
                clean_email,
                first_name,
                last_name,
                item.affiliation or "",
                item.paper_title,
                item.journal,
                str(item.publication_year),
                item.doi or "",
                f"{score.recency_score:.1f}",
                provenance,
            ]
        )

    return _write_safe_csv(rows)


def _write_safe_csv(rows: list[list[str]]) -> bytes:
    """Format and write CSV rows ensuring strict spreadsheet formula safety."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    for row in rows:
        writer.writerow([safe_csv(val) for val in row])
    return buffer.getvalue().encode("utf-8")
