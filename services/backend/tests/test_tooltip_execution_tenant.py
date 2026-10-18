"""Actual SQL authorities for claimed tooltip work; browser bytes are test doubles."""

from collections.abc import Callable
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import CURRENT
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress, Work
from emailmonitor.progress.tooltip import TOOLTIP_URL
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from test_tooltip_execution import browser_observation


class FakeBrowser:
    def __init__(self, during: Callable[[], None] | None = None) -> None:
        self.calls = 0
        self.during = during

    def acquire(
        self, progress: Progress, work: Work, *, context: dict[str, object]
    ) -> ArticleObservation:
        assert CURRENT.get() == work.lease
        assert context["revision"] != 999
        self.calls += 1
        if self.during:
            self.during()
        return browser_observation()


def prepared(
    s: Scenario, *, allow: bool = True, browser_policy: bool = True
) -> tuple[Progress, UUID, Work]:
    with s.client() as client:
        csrf = s.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        operations = [
            "search",
            "fetch_html",
            "extract_contacts",
            "retain_excerpt",
            "export_contacts",
        ]
        if browser_policy:
            operations.append("browser")
        response = client.post(
            source_path(s) + "/policies",
            headers=headers,
            json={"expected_version": 0, "policy": policy_body(allowed_operations=operations)},
        )
        assert response.status_code == 201, response.text
        response = client.post(
            source_path(s) + "/policy-state",
            headers=headers,
            json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
        )
        assert response.status_code == 200, response.text
        ledger = Ledger(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
    body = request_body()
    body["input"] = {"type": "url", "url": TOOLTIP_URL}
    body["options"] = {
        "max_articles": 1,
        "max_search_pages": 1,
        "author_target": "both",
        "allow_browser": allow,
    }
    org = s.organizations[0]
    job = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
    Discovery(ledger.database, ledger.token, SETTINGS).plan(org, job, 1)
    progress = Progress(ledger.database, ledger.token, SETTINGS)
    progress.start(org, job, progress.snapshot(org, job).revision)
    return progress, job, claim(progress, org, job)


def counts(progress: Progress, org: UUID, job: UUID) -> tuple[int, int]:
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        row = c.execute(
            text(
                "SELECT (SELECT count(*) FROM emailmonitor.execution_effects "
                "WHERE organization_id=:org AND job_id=:job), "
                "(SELECT count(*) FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND job_id=:job)"
            ),
            {"org": org, "job": job},
        ).one()
        return int(str(row[0])), int(str(row[1]))


def test_real_upgrade_crash_replay_one_effect_current_revision(scenario: Scenario) -> None:
    progress, job, work = prepared(scenario)
    browser = FakeBrowser()
    executor = ExecutionDispatcher(progress, tooltip=browser)

    def crash() -> None:
        raise RuntimeError("crash after durable browser receipt")

    with pytest.raises(RuntimeError):
        executor.process(replace(work, discovery_revision=999), after_observation=crash)
    org = scenario.organizations[0]
    receipt = progress.extraction.read(org, job)[0]
    assert receipt["revision"] == 2
    assert ArticleObservation.model_validate(receipt["observation"]).route == "browser_dom"
    assert counts(progress, org, job) == (0, 0)
    assert executor.process(work) == "succeeded"
    assert browser.calls == 1
    assert counts(progress, org, job) == (1, 1)
    assert progress.extraction.read(org, job)[0]["observed_at"] == receipt["observed_at"]
    assert progress.snapshot(org, job).state == "completed"


@pytest.mark.parametrize("composed,allow", [(False, True), (True, False)])
def test_real_optout_or_uncomposed_remains_truthful(
    scenario: Scenario, composed: bool, allow: bool
) -> None:
    progress, job, work = prepared(scenario, allow=allow)
    browser = FakeBrowser()
    assert (
        ExecutionDispatcher(progress, tooltip=browser if composed else None).process(work)
        == "unsupported"
    )
    row = progress.extraction.read(scenario.organizations[0], job)[0]
    assert ArticleObservation.model_validate(row["observation"]).status == "requires_browser"
    assert browser.calls == 0
    assert progress.snapshot(scenario.organizations[0], job).state == "completed_partial"


def test_real_missing_browser_policy_keeps_static_without_effect(scenario: Scenario) -> None:
    progress, job, work = prepared(scenario, browser_policy=False)
    browser = FakeBrowser()
    with pytest.raises(AuthorizationDenied):
        ExecutionDispatcher(progress, tooltip=browser).process(work)
    org = scenario.organizations[0]
    assert browser.calls == 0 and counts(progress, org, job) == (0, 0)
    assert (
        ArticleObservation.model_validate(
            progress.extraction.read(org, job)[0]["observation"]
        ).status
        == "requires_browser"
    )


@pytest.mark.parametrize(
    "reason,during",
    [
        (reason, during)
        for reason in ("token", "generation", "pause", "cancel", "policy", "deletion", "expiry")
        for during in (False, True)
    ]
    + [("tenant", False), ("lease_deletion_generation", True)],
)
def test_real_current_fences_before_dispatch_and_before_commit(
    scenario: Scenario, reason: str, during: bool
) -> None:
    progress, job, work = prepared(scenario)
    org = scenario.organizations[0]

    def revoke() -> None:
        if reason in {"pause", "cancel"}:
            progress.control(
                org,
                job,
                progress.snapshot(org, job).revision,
                "pause" if reason == "pause" else "cancel",
            )
        elif reason in {"policy", "deletion"}:
            with scenario.client() as client:
                csrf = scenario.login(client, "owner")
                headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
                if reason == "policy":
                    response = client.post(
                        source_path(scenario) + "/policy-state",
                        headers=headers,
                        json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                    )
                else:
                    response = client.post(
                        f"/api/v1/organizations/{org}/lifecycle",
                        headers=headers,
                        json={"expected_revision": 1, "status": "offboarding"},
                    )
                assert response.status_code == 200, response.text
        else:
            # Administrative test fixture mutates the current server authority,
            # never grants runtime write privileges or changes production code.
            engine = create_engine(scenario.admin_url)
            try:
                with engine.begin() as c:
                    field, value = {
                        "lease_deletion_generation": ("lease_deletion_generation", 999),
                        "token": ("lease_token", uuid4()),
                        "generation": ("lease_generation", 999),
                        "expiry": ("lease_until", "2000-01-01T00:00:00Z"),
                    }[reason]
                    c.execute(
                        text(
                            f"UPDATE emailmonitor.execution_items SET {field}=:value "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        {"value": value, "org": org, "job": job},
                    )
            finally:
                engine.dispose()

    if not during and reason == "tenant":
        work = replace(work, lease=replace(work.lease, organization=scenario.organizations[1]))
    elif not during:
        revoke()
    browser = FakeBrowser(revoke if during else None)
    with pytest.raises((AuthorizationDenied, ValueError)):
        ExecutionDispatcher(progress, tooltip=browser).process(work)
    assert browser.calls == int(during)


def test_real_stale_discovery_revision_refused(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress, job, work = prepared(scenario)
    original = progress.extraction.prepare

    def stale(org: UUID, job: UUID, url: str, *, browser: bool = False) -> dict[str, object]:
        row = original(org, job, url, browser=browser)
        return {**row, "revision": int(str(row["revision"])) - 1} if browser else row

    monkeypatch.setattr(progress.extraction, "prepare", stale)
    browser = FakeBrowser()
    with pytest.raises(HTTPException, match="Discovery revision conflict"):
        ExecutionDispatcher(progress, tooltip=browser).process(work)
    assert browser.calls == 1
    assert counts(progress, scenario.organizations[0], job) == (0, 0)


def test_real_browser_provenance_failure_keeps_static_and_no_effect(scenario: Scenario) -> None:
    progress, job, work = prepared(scenario)

    class ForgedBrowser(FakeBrowser):
        def acquire(
            self, progress: Progress, work: Work, *, context: dict[str, object]
        ) -> ArticleObservation:
            observed = super().acquire(progress, work, context=context)
            return ArticleObservation.model_validate(
                {
                    **observed.model_dump(),
                    "acquisition_digest": "0" * 64,
                }
            )

    browser = ForgedBrowser()
    with pytest.raises(ValueError, match="Registered acquisition provenance required"):
        ExecutionDispatcher(progress, tooltip=browser).process(work)
    assert browser.calls == 1
    assert counts(progress, scenario.organizations[0], job) == (0, 0)
    assert progress.extraction.read(scenario.organizations[0], job)[0]["revision"] == 1


def test_real_callback_cancel_blocks_derive_and_replay(scenario: Scenario) -> None:
    progress, job, work = prepared(scenario)
    org = scenario.organizations[0]
    browser = FakeBrowser()
    executor = ExecutionDispatcher(progress, tooltip=browser)

    def cancel() -> None:
        progress.control(org, job, progress.snapshot(org, job).revision, "cancel")

    with pytest.raises(AuthorizationDenied):
        executor.process(work, after_observation=cancel)
    assert progress.extraction.read(org, job)[0]["revision"] == 2
    assert counts(progress, org, job) == (0, 0)
    with pytest.raises(AuthorizationDenied):
        executor.process(work)
    assert browser.calls == 1


@pytest.mark.parametrize("deadline", ["contact_deadline", "excerpt_deadline"])
def test_real_retained_browser_expiry_refuses_recovery_without_dispatch(
    scenario: Scenario, deadline: str
) -> None:
    progress, job, work = prepared(scenario)
    org = scenario.organizations[0]
    browser = FakeBrowser()
    executor = ExecutionDispatcher(progress, tooltip=browser)

    def crash() -> None:
        raise RuntimeError("crash after durable browser receipt")

    with pytest.raises(RuntimeError, match="crash after durable browser receipt"):
        executor.process(work, after_observation=crash)
    assert progress.extraction.read(org, job)[0]["revision"] == 2
    assert browser.calls == 1 and counts(progress, org, job) == (0, 0)
    admin = create_engine(scenario.admin_url)
    try:
        with admin.begin() as c:
            # Expire the authoritative retained-job deadline. Observation expires_at
            # is immutable/trigger-derived; no trigger or RLS guard is disabled.
            c.execute(
                text(
                    "INSERT INTO emailmonitor.lifecycle_job_deadlines "
                    "(organization_id,job_id,contact_deadline,excerpt_deadline) VALUES "
                    "(:org,:job,clock_timestamp()+interval '90 days',"
                    "clock_timestamp()+interval '30 days') ON CONFLICT DO NOTHING"
                ),
                {"org": org, "job": job},
            )
            c.execute(
                text(
                    f"UPDATE emailmonitor.lifecycle_job_deadlines SET {deadline}="
                    "clock_timestamp()-interval '1 second' "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            )
        with pytest.raises(AuthorizationDenied):
            executor.process(work)
        assert browser.calls == 1
        with admin.begin() as c:
            row = c.execute(
                text(
                    "SELECT revision, observation->>'route' FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
                ),
                {"org": org, "job": job, "url": TOOLTIP_URL},
            ).one()
            assert tuple(row) == (2, "browser_dom")
            for table in ("execution_effects", "association_batches"):
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": job},
                    ).scalar_one()
                    == 0
                )
    finally:
        admin.dispose()
