"""Explicit reuse cannot silently invoke fresh fixture acquisition."""

from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from test_job_contracts import request_body

from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.fetching.safety import IsolationUnavailable
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


def test_missing_provider_reuse_refuses_before_transport() -> None:
    from emailmonitor.progress.provider import ProviderJourney
    from emailmonitor.sources.provider_documents import DOI_URL

    journey = object.__new__(ProviderJourney)
    journey.progress, journey.xml, journey.dispatch = MagicMock(), MagicMock(), MagicMock()
    journey.xml.prepare.return_value = {"reuse_requested": True}
    journey.progress.extraction.read.return_value = []
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", DOI_URL, 1)
    with pytest.raises(AuthorizationDenied):
        journey.process(work)
    journey.dispatch.acquire.assert_not_called()
    journey.progress.associations.derive.assert_not_called()
    journey.progress.finish.assert_not_called()


@pytest.mark.parametrize("case", ["fresh", "missing", "unbound", "wrong_url", "discover", "valid"])
def test_default_worker_provider_reuse_never_enables_transport(case: str) -> None:
    from emailmonitor.sources.provider_documents import DOI_URL, PII_URL

    progress = MagicMock()
    body = {
        **request_body(),
        "input": {"type": "url", "url": PII_URL if case == "wrong_url" else DOI_URL},
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"},
    }
    if case == "fresh":
        del body["reuse"]
    progress.discovery.read_for_work.return_value = (
        {
            "revision": 1,
            "checkpoint": DiscoveryState(
                status="completed",
                reason="single_article",
                articles=[DOI_URL],
                discovery_complete=True,
                completeness="single_article",
            ).model_dump(),
        },
        JobRequest.model_validate(body),
    )
    existing = {
        "article_url": DOI_URL,
        "revision": 1,
        "reused_from_job": UUID(int=6),
        "reused_source_batch": UUID(int=7),
    }
    if case == "unbound":
        existing["reused_source_batch"] = None
    progress.extraction.read.return_value = [] if case == "missing" else [existing]
    progress.associations.derive.return_value = UUID(int=5)
    progress.finish.return_value = "needs_review"
    work = Work(
        Lease(ORG, JOB, ITEM, TOKEN, 1, 1),
        "discover" if case == "discover" else "article",
        DOI_URL,
        1,
    )
    if case == "valid":
        assert Progress.process_fixture(progress, work) == "needs_review"
    else:
        with pytest.raises(IsolationUnavailable if case == "fresh" else AuthorizationDenied):
            Progress.process_fixture(progress, work)
        progress.associations.derive.assert_not_called()
        progress.finish.assert_not_called()
    progress.extraction.fixture.assert_not_called()


@pytest.mark.parametrize("existing", [False, True])
def test_missing_or_unresolved_tooltip_reuse_never_runs_browser(existing: bool) -> None:
    from test_associations import SETTINGS

    from emailmonitor.extraction.fixture import article_bytes
    from emailmonitor.extraction.html import parse_article
    from emailmonitor.progress.tooltip import TOOLTIP_URL, TooltipJourney

    progress, dispatch = MagicMock(), MagicMock()
    progress.extraction.prepare.return_value = {"reuse_requested": True, "revision": 1}
    observation = parse_article(SETTINGS, TOOLTIP_URL, article_bytes("tooltip.html"))
    assert observation.status == "requires_browser"
    progress.extraction.read.return_value = (
        [{"article_url": TOOLTIP_URL, "observation": observation.model_dump(mode="json")}]
        if existing
        else []
    )
    work = Work(Lease(ORG, JOB, ITEM, TOKEN, 1, 1), "article", TOOLTIP_URL, 1)
    with pytest.raises(AuthorizationDenied):
        TooltipJourney(progress, dispatch).process(work)
    progress.extraction.fixture.assert_not_called()
    dispatch.acquire.assert_not_called()
    progress.associations.derive.assert_not_called()


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
