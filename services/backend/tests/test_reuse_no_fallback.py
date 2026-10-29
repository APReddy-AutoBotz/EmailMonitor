"""Explicit reuse cannot silently invoke fresh fixture acquisition."""

from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from test_job_contracts import request_body

from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import Lease
from emailmonitor.progress.service import Progress, Work

ORG, JOB, ITEM, TOKEN = (UUID(int=value) for value in range(1, 5))
URL = "https://synthetic.publisher.example/article-a.html"


@pytest.mark.parametrize("reuse", [False, True])
def test_fresh_acquisition_check_preserves_omitted_default(
    monkeypatch: pytest.MonkeyPatch, reuse: bool
) -> None:
    request = request_body()
    if reuse:
        request["reuse"] = {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"}
    connection = MagicMock()
    progress = MagicMock()
    progress._tenant.return_value = nullcontext(connection)
    monkeypatch.setattr(Ledger, "_lock", lambda *_: {"request": request})
    if reuse:
        with pytest.raises(AuthorizationDenied):
            Progress._require_fresh_acquisition_allowed(progress, ORG, JOB)
    else:
        Progress._require_fresh_acquisition_allowed(progress, ORG, JOB)
    progress._tenant.assert_called_once_with(ORG, Capability.ACQUIRE_SOURCE)


def test_missing_retained_input_refuses_before_fixture_acquisition() -> None:
    progress = MagicMock()
    progress.discovery.read.return_value = {
        "revision": 1,
        "checkpoint": DiscoveryState(
            status="completed",
            reason="single_article",
            articles=[URL],
            discovery_complete=True,
            completeness="single_article",
        ).model_dump(),
    }
    progress.extraction.read.return_value = []
    progress._require_fresh_acquisition_allowed.side_effect = AuthorizationDenied()
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", URL, 1)
    with pytest.raises(AuthorizationDenied):
        Progress.process_fixture(progress, work)
    progress.extraction.fixture.assert_not_called()
    progress.associations.derive.assert_not_called()
    progress.finish.assert_not_called()


def test_existing_observation_is_used_without_fresh_fallback() -> None:
    progress = MagicMock()
    progress.discovery.read.return_value = {
        "revision": 1,
        "checkpoint": DiscoveryState(
            status="completed",
            reason="single_article",
            articles=[URL],
            discovery_complete=True,
            completeness="single_article",
        ).model_dump(),
    }
    progress.extraction.read.return_value = [{"article_url": URL, "revision": 1}]
    progress.associations.derive.return_value = UUID(int=5)
    progress.finish.return_value = "needs_review"
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", URL, 1)
    assert Progress.process_fixture(progress, work) == "needs_review"
    progress._require_fresh_acquisition_allowed.assert_not_called()
    progress.extraction.fixture.assert_not_called()
