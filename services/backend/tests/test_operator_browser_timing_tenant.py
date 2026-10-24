"""The diagnostic reads only existing current-tenant grants on actual SQL."""

import time
from uuid import uuid4

import pytest
from emailmonitor.administration.source import SourceAdmission, SourceLease
from emailmonitor.discovery.service import Discovery
from emailmonitor.fetching.fixture import HOSTS
from emailmonitor.fetching.safety import classify_url
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress
from emailmonitor.sources.policy import Operation
from operator_browser_timing import read_admission_timing
from sqlalchemy import create_engine, text
from sqlalchemy.exc import NoResultFound
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


@pytest.mark.parametrize("terminal", ["finished", "expired", "policy"])
def test_actual_timing_read_is_exact_active_tenant_ticket(
    scenario: Scenario, terminal: str
) -> None:
    org, other = scenario.organizations
    url = classify_url("https://synthetic.publisher.example/tooltip.html", HOSTS)
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        policy = policy_body(
            allowed_operations=[
                "fetch_html",
                "browser",
                "extract_contacts",
                "retain_excerpt",
                "export_contacts",
            ]
        )
        assert (
            client.post(
                path + "/policies", headers=headers, json={"expected_version": 0, "policy": policy}
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        progress = Progress(scenario.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
        request = request_body()
        request["input"] = {"type": "url", "url": url.normalized}
        job = Ledger(progress.database, progress.token, SETTINGS).create(
            org, JobRequest.model_validate(request), str(uuid4())
        )
        Discovery(progress.database, progress.token, SETTINGS).plan(org, job, 1)
        progress.start(org, job, progress.snapshot(org, job).revision)
        work = claim(progress, org, job)
        assert work.lease.job == job
        with bound(work.lease):
            source = SourceAdmission(progress.database, progress.token, SETTINGS)
            ticket = source.acquire(org, 1, Operation.BROWSER, url, time.monotonic() + 15, job)
            deadline = time.monotonic() + 10
            row = read_admission_timing(progress, org, job, 1, ticket, deadline)
            assert row["attempts"] == 1 and abs(float(row["admitted"]) - time.time()) < 5
            for wrong_job, wrong_version, wrong_ticket in [
                (uuid4(), 1, ticket),
                (job, 2, ticket),
                (job, 1, SourceLease(uuid4(), uuid4(), org)),
            ]:
                with pytest.raises(NoResultFound):
                    read_admission_timing(
                        progress, org, wrong_job, wrong_version, wrong_ticket, deadline
                    )
            with pytest.raises(AuthorizationDenied):
                read_admission_timing(
                    progress,
                    other,
                    job,
                    1,
                    SourceLease(ticket.identifier, ticket.nonce, other),
                    deadline,
                )
            if terminal == "finished":
                source.finish(ticket, 200)
            elif terminal == "expired":
                admin = create_engine(scenario.admin_url)
                try:
                    with admin.begin() as connection:
                        connection.execute(
                            text("""UPDATE emailmonitor.source_resource_requests
    SET lease_until=clock_timestamp()-interval '1 second'
    WHERE organization_id=:org AND id=:ticket"""),
                            {"org": org, "ticket": ticket.identifier},
                        )
                finally:
                    admin.dispose()
            else:
                assert (
                    client.post(
                        path + "/policy-state",
                        headers=headers,
                        json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                    ).status_code
                    == 200
                )
            with pytest.raises(NoResultFound):
                read_admission_timing(progress, org, job, 1, ticket, time.monotonic() + 5)
            if terminal != "finished":
                source.finish(ticket)
