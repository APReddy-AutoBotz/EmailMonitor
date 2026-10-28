"""Pure draft checks; no database or current-authority acceptance is implied."""

from uuid import UUID

import pytest
from test_associations import ORG, ORIGIN, SETTINGS

from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.reuse_draft import independent_review_draft
from emailmonitor.extraction.fixture import article_bytes
from emailmonitor.extraction.html import parse_article


def test_rebuilds_from_authored_observation_with_independent_unaccepted_reviews() -> None:
    observed = parse_article(SETTINGS, ORIGIN + "article-a.html", article_bytes("article-a.html"))
    original = map_observation(SETTINGS, ORG, observed)
    assert original.associations[0].state == "accepted"
    source_job, job_a, job_b = UUID(int=1), UUID(int=2), UUID(int=3)
    first = independent_review_draft(SETTINGS, ORG, ORG, source_job, job_a, observed)
    replay = independent_review_draft(SETTINGS, ORG, ORG, source_job, job_a, observed)
    second = independent_review_draft(SETTINGS, ORG, ORG, source_job, job_b, observed)
    assert first == replay and first.associations[0].id != second.associations[0].id
    assert first.associations[0].id != original.associations[0].id
    assert first.associations[0].state == "needs_review" and first.associations[0].revision == 1
    assert first.authors == original.authors and first.candidates == original.candidates
    assert first.evidence == original.evidence and first.content_digest == original.content_digest
    assert first.associations[0].author_id == original.associations[0].author_id
    assert first.associations[0].evidence_ids == original.associations[0].evidence_ids
    assert original.associations[0].state == "accepted"


def test_reuse_draft_is_tenant_scoped_and_rejects_same_job() -> None:
    observed = parse_article(SETTINGS, ORIGIN + "article-a.html", article_bytes("article-a.html"))
    source, target = UUID(int=1), UUID(int=2)
    one = independent_review_draft(SETTINGS, ORG, ORG, source, target, observed)
    two = independent_review_draft(SETTINGS, UUID(int=999), UUID(int=999), source, target, observed)
    assert one.organization_id != two.organization_id
    assert one.associations[0].id != two.associations[0].id
    with pytest.raises(ValueError):
        independent_review_draft(SETTINGS, ORG, ORG, source, source, observed)
    with pytest.raises(ValueError):
        independent_review_draft(SETTINGS, ORG, UUID(int=999), source, target, observed)


def test_bound_pdf_and_xml_cannot_be_relabelled_to_a_different_source_job_or_tenant() -> None:
    from test_pdf_extraction import parse as parse_pdf
    from test_xml_pipeline import retained as retained_xml

    from emailmonitor.extraction.pdf_retained import PdfBinding, retain_pdf

    source_org, source_job, target = UUID(int=1), UUID(int=2), UUID(int=44)
    pdf = retain_pdf(
        parse_pdf("article-a.pdf"),
        PdfBinding(
            organization=source_org,
            job=source_job,
            item=UUID(int=3),
            generation=1,
            deletion_generation=1,
            policy_version=1,
            discovery_revision=1,
        ),
        permit_excerpts=True,
    )
    for observed in (pdf, retained_xml()):
        result = independent_review_draft(
            SETTINGS, source_org, source_org, source_job, target, observed
        )
        assert result.organization_id == source_org
        assert all(a.state != "accepted" for a in result.associations)
        with pytest.raises(ValueError):
            independent_review_draft(
                SETTINGS, source_org, source_org, UUID(int=77), target, observed
            )
        with pytest.raises(ValueError):
            independent_review_draft(
                SETTINGS, UUID(int=88), UUID(int=88), source_job, target, observed
            )
