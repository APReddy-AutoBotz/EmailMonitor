"""Pure candidate shape and time boundaries, not database acceptance."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from emailmonitor.associations.reuse_lineage import ReuseLineageDraft
from pydantic import ValidationError


def fields() -> dict[str, object]:
    observed = datetime(2026, 10, 1, 13, tzinfo=UTC)
    return {
        "organization_id": UUID(int=1),
        "source_job_id": UUID(int=2),
        "target_job_id": UUID(int=3),
        "source_id": "synthetic-publisher",
        "article_url": "https://synthetic.publisher.example/article-a.html",
        "source_revision": 1,
        "source_policy_version": 1,
        "source_generation": 1,
        "deletion_generation": 1,
        "acquisition_digest": "a" * 64,
        "content_digest": "b" * 64,
        "observed_at": observed,
        "expires_at": observed + timedelta(days=1),
        "fresh_since": observed,
        "checked_at": observed + timedelta(hours=1),
    }


def test_inclusive_cutoff_preserves_original_timestamp_and_digest() -> None:
    value = fields()
    value["observed_at"] = datetime(2026, 10, 1, 15, tzinfo=timezone(timedelta(hours=2)))
    candidate = ReuseLineageDraft.model_validate(value)
    assert candidate.observed_at == datetime(2026, 10, 1, 13, tzinfo=UTC)
    assert candidate.fresh_since == candidate.observed_at
    assert candidate.acquisition_digest == "a" * 64
    assert candidate.content_digest == "b" * 64
    with pytest.raises(ValidationError):
        candidate.observed_at = candidate.checked_at


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("target_job_id", UUID(int=2)),
        ("fresh_since", datetime(2026, 10, 1, 13, 0, 1, tzinfo=UTC)),
        ("fresh_since", datetime(2026, 10, 1, 15, tzinfo=UTC)),
        ("checked_at", datetime(2026, 10, 1, 12, tzinfo=UTC)),
        ("expires_at", datetime(2026, 10, 1, 14, tzinfo=UTC)),
        ("observed_at", datetime(2026, 10, 1, 13)),
        ("source_revision", 0),
        ("acquisition_digest", "A" * 64),
        ("content_digest", "b" * 63),
        ("organization_id", str(UUID(int=1))),
    ],
)
def test_invalid_or_stale_candidate_refused(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ReuseLineageDraft.model_validate({**fields(), name: value})


def test_extra_data_is_not_a_lineage_authority() -> None:
    with pytest.raises(ValidationError):
        ReuseLineageDraft.model_validate({**fields(), "authorized": True})
