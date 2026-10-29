"""Explicit reuse cannot silently invoke fresh fixture acquisition."""

from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from test_job_contracts import request_body

from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.binding import Lease
from emailmonitor.progress.service import Progress, Work

ORG, JOB, ITEM, TOKEN = (UUID(int=value) for value in range(1, 5))
URL = "https://synthetic.publisher.example/article-a.html"


def test_work_read_keeps_request_internal_and_uses_one_tenant_transaction() -> None:
    connection, discovery = MagicMock(), MagicMock()
    discovery._tenant.return_value = nullcontext((connection, object()))
    connection.execute.return_value.mappings.return_value.first.return_value = {
        "job_id": JOB,
        "revision": 1,
        "work_request": request_body(),
    }
    checkpoint, request = Discovery.read_for_work(discovery, ORG, JOB)
    assert checkpoint == {"job_id": JOB, "revision": 1}
    assert request.reuse is None
    assert connection.execute.call_count == 1


def test_missing_retained_input_refuses_before_fixture_acquisition() -> None:
    progress = MagicMock()
    request = {
        **request_body(),
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"},
    }
    progress.discovery.read_for_work.return_value = (
        {
            "revision": 1,
            "checkpoint": DiscoveryState(
                status="completed",
                reason="single_article",
                articles=[URL],
                discovery_complete=True,
                completeness="single_article",
            ).model_dump(),
        },
        JobRequest.model_validate(request),
    )
    progress.extraction.read.return_value = []
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", URL, 1)
    with pytest.raises(AuthorizationDenied):
        Progress.process_fixture(progress, work)
    progress.extraction.fixture.assert_not_called()
    progress.associations.derive.assert_not_called()
    progress.finish.assert_not_called()


def test_existing_observation_is_used_without_fresh_fallback() -> None:
    progress = MagicMock()
    request = {
        **request_body(),
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"},
    }
    progress.discovery.read_for_work.return_value = (
        {
            "revision": 1,
            "checkpoint": DiscoveryState(
                status="completed",
                reason="single_article",
                articles=[URL],
                discovery_complete=True,
                completeness="single_article",
            ).model_dump(),
        },
        JobRequest.model_validate(request),
    )
    progress.extraction.read.return_value = [{"article_url": URL, "revision": 1}]
    progress.associations.derive.return_value = UUID(int=5)
    progress.finish.return_value = "needs_review"
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", URL, 1)
    assert Progress.process_fixture(progress, work) == "needs_review"
    progress.extraction.fixture.assert_not_called()


def test_default_fresh_work_still_acquires_without_a_separate_request_read() -> None:
    progress = MagicMock()
    progress.discovery.read_for_work.return_value = (
        {
            "revision": 1,
            "checkpoint": DiscoveryState(
                status="completed",
                reason="single_article",
                articles=[URL],
                discovery_complete=True,
                completeness="single_article",
            ).model_dump(),
        },
        JobRequest.model_validate(request_body()),
    )
    progress.extraction.read.return_value = []
    progress.extraction.fixture.return_value = {"article_url": URL, "revision": 1}
    progress.associations.derive.return_value = UUID(int=5)
    progress.finish.return_value = "needs_review"
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", URL, 1)
    assert Progress.process_fixture(progress, work) == "needs_review"
    progress.extraction.fixture.assert_called_once()
