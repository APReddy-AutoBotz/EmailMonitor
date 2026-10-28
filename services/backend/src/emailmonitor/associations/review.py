"""Pure optimistic review transition; service owns current tenant authorization."""

from emailmonitor.associations.models import Bundle, Review
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.organizations.database import RevisionConflict


def apply_review(settings: Settings, bundle: Bundle, request: Review) -> Bundle:
    require_fixture(settings)
    bundle = Bundle.model_validate_json(bundle.model_dump_json())
    request = Review.model_validate_json(request.model_dump_json())
    current = next((a for a in bundle.associations if a.id == request.association_id), None)
    if current is None:
        raise ValueError("Unavailable association")
    if current.revision != request.expected_revision:
        raise RevisionConflict()
    if current.state == "suppressed":
        raise ValueError("Suppression cannot be overridden by review")
    if len(set(request.evidence_ids)) != len(request.evidence_ids):
        raise ValueError("Distinct cited evidence required")
    known = {e.id: e for e in bundle.evidence}
    if not set(request.evidence_ids) <= known.keys():
        raise ValueError("Cited evidence must belong to this source observation")
    author = request.author_id if request.author_id is not None else current.author_id
    if request.action == "correct" and request.author_id is None:
        raise ValueError("Correction requires an observed author instance")
    if request.action == "reject" and request.author_id is not None:
        raise ValueError("Rejection cannot silently change identity")
    if request.action == "unlink" and (
        request.author_id is not None
        or current.author_id is None
        or request.evidence_ids != current.evidence_ids
    ):
        raise ValueError("Unlink requires a linked author and unchanged retained evidence")
    candidate = next(c for c in bundle.candidates if c.id == current.candidate_id)
    if not set(candidate.evidence_ids) & set(request.evidence_ids):
        raise ValueError("Review requires cited observed address evidence")
    update: dict[str, object] = {
        "state": "needs_review"
        if request.action == "unlink"
        else "rejected"
        if request.action == "reject"
        else "accepted",
        "reason": "reviewed_unlinked" if request.action == "unlink" else "reviewed_evidence",
        "revision": current.revision + 1,
        "evidence_ids": request.evidence_ids,
    }
    if request.action == "unlink":
        update.update(author_id=None, evidence_strength="ambiguous")
    elif request.action != "reject":
        observed = next((a for a in bundle.authors if a.id == author), None)
        if (
            observed is None
            or not set(observed.evidence_ids) & set(request.evidence_ids)
            or not all(known[i].excerpt for i in request.evidence_ids)
        ):
            raise ValueError("Acceptance requires retained observed author/address evidence")
        update.update(author_id=author, evidence_strength="supported")
    revised = current.model_copy(update=update)
    result = bundle.model_copy(
        update={
            "associations": tuple(revised if a.id == current.id else a for a in bundle.associations)
        }
    )
    return Bundle.model_validate_json(result.model_dump_json())
