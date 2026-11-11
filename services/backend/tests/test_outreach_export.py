"""Tests for cold outreach export formatting, recency scoring, and GDPR provenance."""

import pytest

from emailmonitor.results.outreach import (
    ContactExportItem,
    evaluate_contact,
    generate_gdpr_provenance,
    render_instantly_csv,
    render_smartlead_csv,
    split_author_name,
)
from emailmonitor.results.render import RenderDenied


def test_split_author_name():
    assert split_author_name("Dr. Marcus Vance") == ("Marcus", "Vance")
    assert split_author_name("Prof. Elena Rostova, Ph.D.") == ("Elena", "Rostova")
    assert split_author_name("Soo-Jin Kim") == ("Soo-Jin", "Kim")
    assert split_author_name("Aristotle") == ("Aristotle", "")
    assert split_author_name("") == ("", "")
    assert split_author_name(None) == ("", "")


def test_evaluate_contact_scoring():
    item_recent = ContactExportItem(
        raw_email="marcus.vance@biotech.ethz.ch",
        display_name="Marcus Vance",
        paper_title="Advances in CRISPR",
        journal="PLOS Biology",
        publication_year=2026,
    )
    score_recent = evaluate_contact(item_recent, reference_year=2026)
    assert score_recent.outreach_eligible is True
    assert score_recent.domain_type == "institutional"
    assert score_recent.recency_level == "active_recent"
    assert score_recent.recency_score == 1.0

    item_moderate = ContactExportItem(
        raw_email="researcher@gmail.com",
        display_name="John Doe",
        paper_title="Older Study",
        journal="Nature",
        publication_year=2024,
    )
    score_moderate = evaluate_contact(item_moderate, reference_year=2026)
    assert score_moderate.outreach_eligible is True
    assert score_moderate.domain_type == "commercial_free"
    assert score_moderate.recency_level == "moderate"
    assert score_moderate.recency_score == 0.8

    item_disposable = ContactExportItem(
        raw_email="fake@mailinator.com",
        paper_title="Spam Paper",
        journal="Predatory Journal",
        publication_year=2026,
    )
    score_disp = evaluate_contact(item_disposable, reference_year=2026)
    assert score_disp.outreach_eligible is False
    assert score_disp.domain_type == "disposable"
    assert score_disp.rejection_reason == "disposable_domain_prohibited"

    item_invalid = ContactExportItem(
        raw_email="invalid-syntax-at-nowhere",
        paper_title="Test",
        journal="Test",
        publication_year=2026,
    )
    score_inv = evaluate_contact(item_invalid, reference_year=2026)
    assert score_inv.outreach_eligible is False
    assert score_inv.rejection_reason == "invalid_email_syntax"


def test_gdpr_provenance():
    item = ContactExportItem(
        raw_email="marcus.vance@biotech.ethz.ch",
        paper_title="Advances in CRISPR",
        journal="PLOS Biology",
        publication_year=2026,
        doi="10.1371/journal.pbio.3002145",
    )
    notice = generate_gdpr_provenance(item)
    assert "Advances in CRISPR" in notice
    assert "PLOS Biology" in notice
    assert "2026" in notice
    assert "10.1371/journal.pbio.3002145" in notice
    assert "GDPR Article 6(1)(f) Legitimate Interest" in notice


def test_render_instantly_csv():
    items = [
        ContactExportItem(
            raw_email="marcus.vance@biotech.ethz.ch",
            display_name="Dr. Marcus Vance",
            affiliation="ETH Zurich",
            paper_title="Advances in CRISPR",
            journal="PLOS Biology",
            publication_year=2026,
            doi="10.1371/journal.pbio.3002145",
        ),
        ContactExportItem(
            raw_email="suppressed.author@example.edu",
            display_name="Opted Out",
            paper_title="Some Study",
            journal="Science",
            publication_year=2026,
        ),
    ]

    # Test with suppression
    csv_bytes = render_instantly_csv(
        items,
        suppressed_emails={"suppressed.author@example.edu"},
        reference_year=2026,
    )
    csv_text = csv_bytes.decode("utf-8")

    assert "email" in csv_text
    assert "first_name" in csv_text
    assert "custom_gdpr_receipt" in csv_text
    assert "marcus.vance@biotech.ethz.ch" in csv_text
    assert "Marcus" in csv_text
    assert "Vance" in csv_text
    assert "ETH Zurich" in csv_text
    # Suppressed email must NOT be present!
    assert "suppressed.author@example.edu" not in csv_text


def test_render_smartlead_csv():
    items = [
        ContactExportItem(
            raw_email="kim.soojin@cropgenomics.ac.kr",
            display_name="Soo-Jin Kim",
            affiliation="National Institute of Crop Science",
            paper_title="Wheat Transcriptomics",
            journal="BMC Genomics",
            publication_year=2026,
            doi="10.1186/s12864-026-09123-x",
        )
    ]
    csv_bytes = render_smartlead_csv(items, reference_year=2026)
    csv_text = csv_bytes.decode("utf-8")

    assert "Email" in csv_text
    assert "Custom_Recency_Score" in csv_text
    assert "kim.soojin@cropgenomics.ac.kr" in csv_text
    assert "Soo-Jin" in csv_text
    assert "1.0" in csv_text


def test_csv_formula_injection_defense():
    unsafe_item = [
        ContactExportItem(
            raw_email="evil@example.org",
            display_name="=CMD|' /C calc'!A0",
            paper_title="Unsafe Paper",
            journal="Journal",
            publication_year=2026,
        )
    ]
    with pytest.raises(RenderDenied, match="unsafe_csv_cell"):
        render_instantly_csv(unsafe_item)
