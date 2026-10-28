"""Pure review decisions cite observed facts and use optimistic revisions."""

from uuid import UUID

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.associations.review import apply_review
from emailmonitor.organizations.database import RevisionConflict
from pydantic import ValidationError
from test_associations import ORG, SETTINGS, html


def request(**changes: object) -> Review:
    value = html("article-a.html")
    association = value.associations[0]
    payload: dict[str, object] = {
        "association_id": association.id,
        "expected_revision": 1,
        "action": "accept",
        "evidence_ids": association.evidence_ids,
        "reason": "Authored explicit correspondence",
    }
    payload.update(changes)
    return Review.model_validate(payload)


def test_evidence_backed_accept_and_reject_preserve_roles_and_technical_unknowns() -> None:
    bundle = html("article-a.html")
    accepted = apply_review(SETTINGS, bundle, request())
    assert accepted.associations[0].revision == 2
    assert accepted.associations[0].state == "accepted"
    assert accepted.associations[0].reason == "reviewed_evidence"
    assert accepted.authors == bundle.authors and accepted.candidates == bundle.candidates
    assert accepted.candidates[0].address.delivery_status == "unverified"
    rejected = apply_review(SETTINGS, accepted, request(action="reject", expected_revision=2))
    assert rejected.associations[0].state == "rejected" and rejected.associations[0].revision == 3
    assert bundle.associations[0].revision == 1


def test_correction_only_selects_observed_article_local_author_with_cited_evidence() -> None:
    bundle = html("article-a.html")
    cited = tuple(
        dict.fromkeys((*bundle.candidates[0].evidence_ids, *bundle.authors[0].evidence_ids))
    )
    corrected = apply_review(
        SETTINGS,
        bundle,
        request(
            action="correct",
            author_id=bundle.authors[0].id,
            evidence_ids=cited,
            reason="Synthetic reviewer correction, retained cited facts",
        ),
    )
    assert corrected.associations[0].author_id == bundle.authors[0].id
    assert corrected.associations[0].state == "accepted"
    assert corrected.authors[0].corresponding is None  # review does not rewrite extracted roles
    assert corrected.authors[1].corresponding is True


@pytest.mark.parametrize(
    "change",
    [
        {"association_id": UUID(int=2)},
        {"author_id": UUID(int=3)},
        {"action": "correct"},
        {"action": "reject", "author_id": UUID(int=3)},
        {"evidence_ids": (UUID(int=4),)},
    ],
)
def test_unknown_uncited_and_silent_identity_mutations_refuse(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        apply_review(SETTINGS, html("article-a.html"), request(**change))


def test_stale_revision_is_conflict_and_cross_tenant_evidence_is_not_reusable() -> None:
    with pytest.raises(RevisionConflict):
        apply_review(SETTINGS, html("article-a.html"), request(expected_revision=2))
    other = html("article-a.html", org=UUID(int=2))
    with pytest.raises(ValueError):
        apply_review(
            SETTINGS,
            html("article-a.html", org=ORG),
            request(evidence_ids=other.associations[0].evidence_ids),
        )


def test_free_text_address_is_not_a_review_input() -> None:
    with pytest.raises(ValidationError):
        request(raw_address="new@example.org")


def test_duplicate_or_author_only_citations_refuse() -> None:
    bundle = html("article-a.html")
    with pytest.raises(ValueError):
        apply_review(SETTINGS, bundle, request(evidence_ids=(bundle.evidence[0].id,) * 2))
    with pytest.raises(ValueError):
        apply_review(SETTINGS, bundle, request(evidence_ids=bundle.authors[0].evidence_ids))


def test_unlink_preserves_observations_and_requires_explicit_reacceptance() -> None:
    original = html("article-a.html")
    accepted = apply_review(SETTINGS, original, request())
    before = accepted.associations[0]
    unlinked = apply_review(
        SETTINGS,
        accepted,
        request(action="unlink", expected_revision=2, evidence_ids=before.evidence_ids),
    )
    result = unlinked.associations[0]
    assert (result.state, result.reason, result.author_id, result.revision) == (
        "needs_review",
        "reviewed_unlinked",
        None,
        3,
    )
    assert result.evidence_strength == "ambiguous" and result.evidence_ids == before.evidence_ids
    assert unlinked.evidence == accepted.evidence
    assert unlinked.authors == accepted.authors and unlinked.candidates == accepted.candidates
    with pytest.raises(ValueError):
        apply_review(
            SETTINGS, unlinked, request(expected_revision=3, evidence_ids=result.evidence_ids)
        )
    restored = apply_review(
        SETTINGS,
        unlinked,
        request(
            action="correct",
            expected_revision=3,
            author_id=before.author_id,
            evidence_ids=result.evidence_ids,
        ),
    )
    assert restored.associations[0].state == "accepted" and restored.associations[0].revision == 4


def test_unlink_refuses_stale_or_changed_evidence_and_identity() -> None:
    original = html("article-a.html")
    accepted = apply_review(SETTINGS, original, request())
    before = accepted.associations[0]
    with pytest.raises(RevisionConflict):
        apply_review(SETTINGS, accepted, request(action="unlink", expected_revision=1))
    with pytest.raises(ValueError):
        apply_review(
            SETTINGS,
            accepted,
            request(action="unlink", expected_revision=2, author_id=before.author_id),
        )
    with pytest.raises(ValueError):
        apply_review(
            SETTINGS,
            accepted,
            request(action="unlink", expected_revision=2, evidence_ids=(accepted.evidence[0].id,)),
        )
    unlinked = apply_review(SETTINGS, accepted, request(action="unlink", expected_revision=2))
    with pytest.raises(ValueError):
        apply_review(SETTINGS, unlinked, request(action="unlink", expected_revision=3))
