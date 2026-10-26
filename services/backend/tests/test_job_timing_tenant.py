"""Actual SQL timing projection through unchanged job authority and lifecycle fences."""

import pytest
from emailmonitor.organizations.database import AuthorizationDenied
from sqlalchemy import create_engine, text
from test_progress_tenant import claim, drain, planned
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_real_terminal_interval_replay_and_tenant_refusal(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    assert progress.timing(org, job).availability == "not_started"
    progress.start(org, job, progress.snapshot(org, job).revision)
    assert progress.timing(org, job).availability == "not_terminal"
    drain(progress, org, job)
    value = progress.timing(org, job)
    events = progress.events(org, job, 0)
    assert value.availability == "recorded"
    assert value.queued_at == events[0].occurred_at
    assert value.terminal_at == events[-1].occurred_at
    assert value.elapsed_seconds == (events[-1].occurred_at - events[0].occurred_at).total_seconds()
    assert progress.timing(org, job) == value
    with pytest.raises(AuthorizationDenied):
        progress.timing(scenario.organizations[1], job)
    with scenario.client() as client:
        scenario.login(client, "owner")
        response = client.get(f"/api/v1/organizations/{org}/jobs/{job}/timing")
        assert response.status_code == 200
        assert response.json() == value.model_dump(mode="json")


def test_real_pause_resume_cancel_preserves_first_queue(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    first = progress.events(org, job, 0)[0].occurred_at
    for action in ("pause", "resume", "cancel"):
        progress.control(org, job, progress.snapshot(org, job).revision, action)
    value = progress.timing(org, job)
    assert value.availability == "recorded" and value.state == "cancelled"
    assert value.queued_at == first


def test_real_continuation_has_own_interval_without_rewriting_original(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    for _ in range(3):
        progress.finish(claim(progress, org, job), failure="worker_failure")
    before = progress.timing(org, job)
    assert before.availability == "recorded"
    continuation = progress.retry(org, job, progress.snapshot(org, job).revision)
    assert continuation != job
    assert progress.timing(org, continuation).availability == "not_terminal"
    assert progress.timing(org, job) == before
    drain(progress, org, continuation)
    after = progress.timing(org, continuation)
    assert after.availability == "recorded" and after.job_id != before.job_id
    assert after.queued_at is not None and before.terminal_at is not None
    assert after.queued_at >= before.terminal_at
    assert progress.timing(org, job) == before


def test_real_expired_execution_refuses_timing(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    assert progress.timing(org, job).availability == "recorded"
    engine = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""UPDATE emailmonitor.execution_runs
SET expires_at=clock_timestamp()-interval '1 second'
WHERE organization_id=:org AND job_id=:job"""),
                {"org": org, "job": job},
            )
    finally:
        engine.dispose()
    with pytest.raises(AuthorizationDenied):
        progress.timing(org, job)
