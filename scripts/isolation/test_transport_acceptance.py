"""Actual controlled-network acceptance; runs only after independent CI review."""

import json
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from emailmonitor.config import Settings
from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.fixture import DIGESTS
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.service import Extraction
from emailmonitor.fetching.fixture import HOSTS, TenantFixtureAuthorization
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress
from emailmonitor.sources.policy import Operation
from run_browser_acceptance import conversation
from sqlalchemy import text
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from transport_manifest import ENDPOINTS, HOST
from transport_rpc import BrowserProxyMediator, GatewayProxy
from transport_topology import Topology, docker


@pytest.fixture(scope="module")
def topology() -> Iterator[Topology]:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("EM_REQUIRE_CONTROLLED_NETWORK") != "true"
    ):
        pytest.fail("Required reviewed disposable CI acceptance environment missing")
    value = Topology()
    try:
        value.start()
        yield value
        value.inspect()
        for role, process in value.processes.items():
            deadline = time.monotonic() + 5
            process.send({"kind": "inspect"}, deadline)
            inspected = process.receive(deadline)
            assert inspected["kind"] == "inspected" and inspected["evidence"]["role"] == role
            print(json.dumps(inspected), flush=True)
            process.send({"kind": "stop"}, deadline)
            stopped = process.receive(deadline)
            assert stopped["kind"] == "stopped"
            assert not stopped.get("failures")
            assert process.process.wait(timeout=10) == 0
            state = json.loads(docker("inspect", value.identifiers[role]).stdout)[0]["State"]
            assert not state["Running"] and not state["OOMKilled"] and state["ExitCode"] == 0
    finally:
        value.close()


def configure(topology: Topology, mode: str = "normal") -> None:
    for role in ("fixture-a", "fixture-b"):
        deadline = time.monotonic() + 5
        process = topology.processes[role]
        process.send({"mode": mode}, deadline)
        assert process.receive(deadline) == {"kind": "configured"}


def snapshot(topology: Topology, role: str = "fixture-a") -> dict[str, Any]:
    process = topology.processes[role]
    deadline = time.monotonic() + 5
    process.send({"kind": "snapshot"}, deadline)
    value = process.receive(deadline)
    assert value["kind"] == "snapshot" and not value["failures"]
    assert all(set(call["headers"]) == {"Host", "Accept", "Connection"} for call in value["calls"])
    return value


def proxy(
    topology: Topology,
    organization: UUID,
    authorize: object = None,
    family: int = 4,
    ca: str = "fixture",
    *,
    resources: HopResources | None = None,
    diagnostic_transport_only: bool = False,
) -> GatewayProxy:
    tenant = isinstance(authorize, TenantFixtureAuthorization)
    if (
        type(diagnostic_transport_only) is not bool
        or (tenant and diagnostic_transport_only)
        or (not tenant and (resources is not None or not diagnostic_transport_only))
    ):
        raise FetchDenied("source_resource_boundary_required")

    def scope(operation: Operation) -> PlanScope:
        return PlanScope(
            organization,
            "synthetic-publisher",
            1,
            operation,
            HOSTS,
            time.monotonic() + (19 if isinstance(authorize, TenantFixtureAuthorization) else 4.5),
            2,
        )

    def check(bound: PlanScope, url: SafeURL) -> None:
        assert (
            bound.organization == organization
            and bound.source == "synthetic-publisher"
            and bound.policy_version == 1
        )
        if callable(authorize):
            authorize(url, bound.operation)

    return GatewayProxy(
        topology.processes["gateway"],
        scope,
        check,
        family,
        ca,
        resources=resources
        if resources is not None
        else authorize.resources
        if isinstance(authorize, TenantFixtureAuthorization)
        else None,
        diagnostic_transport_only=diagnostic_transport_only,
    )


class CompletionResources:
    """Trusted test hook retains real admission before and after observed response."""

    def __init__(self, resources: HopResources, before_success: Callable[[], None]) -> None:
        self._resources, self._before_success = resources, before_success

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        return self._resources.acquire(url, operation, deadline)

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        if status == 200:
            self._before_success()
        self._resources.finish(ticket, status, retry_after)


@pytest.mark.parametrize("family", [4, 6])
def test_actual_dns_selected_literal_tls_family(topology: Topology, family: int) -> None:
    configure(topology)
    target = proxy(
        topology,
        UUID("11111111-1111-4111-8111-111111111111"),
        family=family,
        diagnostic_transport_only=True,
    )
    assert b"synthetic marker" in target.fetch(f"https://{HOST}/tooltip.html")
    assert target.peers == [[ENDPOINTS["fixture-a"][family == 6], 443, HOST]]
    assert target.authorizations >= 4
    observations = snapshot(topology)
    assert len(observations["calls"]) == 1 and len(observations["queries"]) == 2
    assert observations["calls"][0]["sni"] == HOST
    assert set(observations["calls"][0]["headers"]) == {"Host", "Accept", "Connection"}
    print(
        json.dumps({"case": "actual_literal_tls", "family": family, "peers": target.peers}),
        flush=True,
    )


def test_actual_redirect_fresh_dns_and_peer(topology: Topology) -> None:
    configure(topology, "redirect")
    target = proxy(
        topology,
        UUID("11111111-1111-4111-8111-111111111111"),
        diagnostic_transport_only=True,
    )
    assert b"synthetic marker" in target.fetch(f"https://{HOST}/redirect.html")
    assert target.peers == [
        [ENDPOINTS["fixture-a"][0], 443, HOST],
        [ENDPOINTS["fixture-b"][0], 443, HOST],
    ]
    assert len(snapshot(topology)["queries"]) == 4
    assert len(snapshot(topology)["calls"]) == len(snapshot(topology, "fixture-b")["calls"]) == 1
    print(
        json.dumps({"case": "redirect_dns_selected_peer_change", "peers": target.peers}),
        flush=True,
    )


@pytest.mark.parametrize("mode", ["mixed", "private"])
def test_actual_dns_whole_snapshot_denies_before_tcp(topology: Topology, mode: str) -> None:
    configure(topology, mode)
    with pytest.raises(FetchDenied):
        proxy(
            topology,
            UUID("11111111-1111-4111-8111-111111111111"),
            diagnostic_transport_only=True,
        ).fetch(f"https://{HOST}/tooltip.html")
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2


@pytest.mark.parametrize("path", ["forbidden.html", "off-domain.html", "large.html"])
def test_actual_http_failure_no_retry_or_escape(topology: Topology, path: str) -> None:
    configure(topology)
    with pytest.raises(FetchDenied):
        proxy(
            topology,
            UUID("11111111-1111-4111-8111-111111111111"),
            diagnostic_transport_only=True,
        ).fetch(f"https://{HOST}/{path}")
    assert len(snapshot(topology)["calls"]) == 1
    assert len(snapshot(topology)["queries"]) == 2


def test_actual_untrusted_tls_certificate_is_not_released(topology: Topology) -> None:
    configure(topology)
    with pytest.raises(FetchDenied):
        proxy(
            topology,
            UUID("11111111-1111-4111-8111-111111111111"),
            ca="untrusted",
            diagnostic_transport_only=True,
        ).fetch(f"https://{HOST}/tooltip.html")
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2


def test_actual_trusted_ca_wrong_hostname_is_not_released(topology: Topology) -> None:
    configure(topology, "wrong_name")
    with pytest.raises(FetchDenied):
        proxy(
            topology,
            UUID("11111111-1111-4111-8111-111111111111"),
            diagnostic_transport_only=True,
        ).fetch(f"https://{HOST}/tooltip.html")
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2


def test_actual_rebinding_cannot_re_resolve_a_selected_socket(
    topology: Topology,
) -> None:
    configure(topology, "rebinding")
    target = proxy(
        topology,
        UUID("11111111-1111-4111-8111-111111111111"),
        diagnostic_transport_only=True,
    )
    assert b"synthetic marker" in target.fetch(f"https://{HOST}/tooltip.html")
    assert target.peers == [[ENDPOINTS["fixture-a"][0], 443, HOST]]
    assert len(snapshot(topology)["calls"]) == 1
    assert len(snapshot(topology)["queries"]) == 2
    with pytest.raises(FetchDenied):
        target.fetch(f"https://{HOST}/tooltip.html")
    assert len(snapshot(topology)["calls"]) == 1
    assert len(snapshot(topology)["queries"]) == 4


def test_actual_browser_gateway_current_tenant_policy(
    topology: Topology, scenario: Scenario
) -> None:
    configure(topology)
    browser = topology.browser()
    with scenario.client() as client, ExitStack() as work_scope:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        body = policy_body(
            allowed_operations=[
                "fetch_html",
                "browser",
                "retain_excerpt",
                "export_contacts",
                "search",
                "extract_contacts",
            ]
        )
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": body},
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={
                    "expected_version": 1,
                    "expected_revision": 1,
                    "state": "approved",
                },
            ).status_code
            == 200
        )
        token = str(client.cookies[COOKIE])
        from test_job_contracts import request_body

        request = request_body()
        request["input"] = {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        }
        request["options"] = {
            "max_articles": 500,
            "max_search_pages": 2,
            "author_target": "both",
        }
        settings = Settings(environment="test", fixture_mode=True)
        org = scenario.organizations[0]
        ledger = Ledger(scenario.foundation.database, token, settings)
        job = ledger.create(org, JobRequest.model_validate(request), str(uuid4()))
        discovery = Discovery(ledger.database, token, settings)
        discovery.plan(org, job, 1)
        step_fixture(discovery, org, job, 1)
        step_fixture(discovery, org, job, 2)
        extraction = Extraction(ledger.database, token, settings)
        pending = extraction.fixture(org, job, f"https://{HOST}/tooltip.html", 3)
        assert (
            ArticleObservation.model_validate(pending["observation"]).status == "requires_browser"
        )
        execution = Progress(ledger.database, token, settings)
        execution.start(org, job, execution.snapshot(org, job).revision)
        with ledger.database.tenant(token, org, Capability.READ_ORGANIZATION) as (
            connection,
            _,
        ):
            tooltip_item: UUID = connection.execute(
                text(
                    "SELECT id FROM emailmonitor.execution_items WHERE organization_id=:org "
                    "AND job_id=:job AND input_url=:url"
                ),
                {"org": org, "job": job, "url": f"https://{HOST}/tooltip.html"},
            ).scalar_one()
        message = next(row for row in execution.pending(org) if row["item_id"] == tooltip_item)
        browser_work = execution.claim(
            org, job, tooltip_item, UUID(str(message["event_id"])), seconds=120
        )
        assert browser_work is not None
        work_scope.enter_context(bound(browser_work.lease))
        assert execution.snapshot(org, job).state == "running"
        extraction.prepare(org, job, f"https://{HOST}/tooltip.html", browser=True)
        allow = TenantFixtureAuthorization(
            scenario.foundation.database,
            token,
            scenario.organizations[0],
            "synthetic-publisher",
            1,
        )
        target = proxy(topology, scenario.organizations[0], allow)
        mediator = BrowserProxyMediator(target)
        evidence = conversation(browser, mediator)
        article = ArticleObservation.model_validate(evidence.pop("article_observation"))
        assert article.authors[0].display_name == "Elena Park"
        assert article.authors[0].first and article.authors[0].corresponding
        assert article.candidates[0].raw_address == "elena.park@example.org"
        assert article.candidates[0].author_positions == [1]
        saved = extraction.commit(
            org,
            job,
            article,
            expected_revision=3,
            source_digest=DIGESTS["tooltip.html"],
        )
        assert saved["revision"] == 2
        assert ArticleObservation.model_validate(saved["observation"]).status == "observed"
        assert (
            extraction.commit(
                org,
                job,
                article,
                expected_revision=3,
                source_digest=DIGESTS["tooltip.html"],
            )["revision"]
            == 2
        )
        batch = execution.associations.derive(org, job, article.url, 2)
        assert execution.finish(browser_work, batch) == "succeeded"
        work_scope.close()
        for _ in range(4):
            remaining = execution.pending(org)
            if not remaining:
                break
            row = remaining[0]
            work = execution.claim(org, job, UUID(str(row["item_id"])), UUID(str(row["event_id"])))
            assert work is not None
            execution.process_fixture(work)
        completed = execution.snapshot(org, job)
        assert completed.state == "completed" and completed.counts.terminal == 4
        evidence["durable_browser_item_succeeded"] = True
        evidence["durable_job_completed"] = True
        evidence["observed_authors"] = len(article.authors)
        evidence["observed_candidates"] = len(article.candidates)
        evidence["observation_persisted"] = True
        actual_browser_peers = [list(peer) for peer in mediator.selected_peers]
        assert actual_browser_peers == [[ENDPOINTS["fixture-a"][0], 443, HOST]] * 2
        observations = snapshot(topology)
        assert len(observations["calls"]) == 2 and len(observations["queries"]) == 4
        assert (
            observations["calls"][1]["received_monotonic"]
            - observations["calls"][0]["received_monotonic"]
            >= 4.9
        )
        with scenario.foundation.database.tenant(token, org, Capability.READ_ORGANIZATION) as (
            connection,
            _,
        ):
            operational: dict[str, Any] = connection.execute(
                text("SELECT emailmonitor.administration_usage(:org)"), {"org": org}
            ).scalar_one()
            assert operational["source_resource_attempts"] == 2
            assert operational["active_units"].get("browser", 0) == 0
        evidence["source_throttle_verified"] = True
        evidence["source_attempts"] = 2
        assert all(
            call["sni"] == HOST and set(call["headers"]) == {"Host", "Accept", "Connection"}
            for call in observations["calls"]
        )
        assert mediator.accepted == 2 and mediator.denied >= 7
        denied = TenantFixtureAuthorization(
            scenario.foundation.database,
            token,
            scenario.organizations[1],
            "synthetic-publisher",
            1,
        )
        with pytest.raises(FetchDenied):
            proxy(topology, scenario.organizations[1], denied).fetch(
                f"https://{HOST}/tooltip.html", Operation.BROWSER
            )
        assert len(snapshot(topology)["calls"]) == 2
        assert len(snapshot(topology)["queries"]) == 4
        stale = TenantFixtureAuthorization(
            scenario.foundation.database,
            token,
            scenario.organizations[0],
            "synthetic-publisher",
            2,
        )
        with pytest.raises(FetchDenied):
            proxy(topology, scenario.organizations[0], stale).fetch(
                f"https://{HOST}/tooltip.html", Operation.BROWSER
            )
        assert len(snapshot(topology)["queries"]) == 4
        revoked = [False]

        def revoke_at_observed_completion() -> None:
            # Completion is emitted only after a received HTTP response. Require
            # the actual new receipt, rather than guessing authorization counts.
            acquired = snapshot(topology)
            assert len(acquired["calls"]) == 3
            assert acquired["calls"][-1]["path"] == "/tooltip.html"
            assert not revoked[0]
            assert (
                client.post(
                    path + "/policy-state",
                    headers=headers,
                    json={
                        "expected_version": 1,
                        "expected_revision": 2,
                        "state": "revoked",
                    },
                ).status_code
                == 200
            )
            revoked[0] = True

        inflight = proxy(
            topology,
            scenario.organizations[0],
            allow,
            resources=CompletionResources(allow.resources, revoke_at_observed_completion),
        )
        with pytest.raises(FetchDenied):
            inflight.fetch(f"https://{HOST}/tooltip.html", Operation.BROWSER)
        assert revoked[0] is True
        assert len(snapshot(topology)["calls"]) == 3
        with pytest.raises(FetchDenied):
            target.fetch(f"https://{HOST}/tooltip.html", Operation.BROWSER)
        print(
            json.dumps(
                {
                    **evidence,
                    "actual_tenant_policy": True,
                    "cross_tenant_denied": True,
                    "revocation_denied": True,
                    "actual_dns_selected_peers": actual_browser_peers,
                }
            ),
            flush=True,
        )


def wait_for_held_receipt(
    topology: Topology, pending: Future[bytes], deadline: float
) -> dict[str, Any]:
    """Bounded fixed-fixture observation; a failed fetch cannot consume control frames."""
    for _ in range(50):
        if time.monotonic() >= deadline:
            break
        if pending.done():
            pending.result()
            raise AssertionError("Synthetic response completed before held receipt")
        calls = snapshot(topology)["calls"]
        if calls:
            return cast(dict[str, Any], calls[0])
        # At most50 observations within the original10-second budget; fixture's
        # existing128-frame control cap and all response deadlines stay unchanged.
        time.sleep(0.2)
    raise AssertionError("Actual synthetic HTTPS request never arrived")


def test_actual_blocked_source_preserves_another_tenants_processing_and_export_pool(
    topology: Topology,
    scenario: Scenario,
) -> None:
    from emailmonitor.administration.service import Administration
    from emailmonitor.administration.source import SourceAdmission
    from emailmonitor.fetching.safety import classify_url
    from emailmonitor.results.service import Results
    from test_admission_tenant import run_until_terminal, tenant_b
    from test_progress_tenant import planned
    from test_results_tenant import options

    progress, _ = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    other, job = tenant_b(scenario)
    org, other_org = scenario.organizations
    allow = TenantFixtureAuthorization(
        progress.database, progress.token, org, "synthetic-publisher", 1
    )
    target = proxy(topology, org, allow)
    configure(topology, "slow")
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(target.fetch, f"https://{HOST}/tooltip.html")
        deadline = time.monotonic() + 10
        first_receipt = wait_for_held_receipt(topology, pending, deadline)
        assert not pending.done()
        resource = Administration(progress.database, progress.token, progress.settings).usage(org)
        assert resource.active_units["http"] == 1 and resource.source_resource_attempts == 1
        url = classify_url(f"https://{HOST}/tooltip.html", HOSTS)
        with pytest.raises(FetchDenied):
            SourceAdmission(other.database, other.token, other.settings).acquire(
                other_org,
                1,
                Operation.HTML,
                url,
                time.monotonic() + 0.5,
            )
        assert (
            Administration(other.database, other.token, other.settings)
            .usage(other_org)
            .source_resource_attempts
            == 0
        )
        other.start(other_org, job, other.snapshot(other_org, job).revision)
        run_until_terminal(other, other_org, job)
        results = Results(other.database, other.token, other.settings)
        export = results.create(other_org, options(job), str(uuid4()))
        row = results.pending(other_org)[0]
        lease = results.claim(
            other_org,
            export.id,
            UUID(str(row["event_id"])),
            int(str(row["generation"])),
        )
        assert lease is not None and results.process(lease)
        assert results.download(other_org, export.id).body
        # Genuine work/artifact completed while the first actual HTTP body was held.
        assert not pending.done()
        release_deadline = time.monotonic() + 5
        topology.processes["fixture-a"].send({"kind": "release"}, release_deadline)
        assert topology.processes["fixture-a"].receive(release_deadline) == {"kind": "released"}
        assert b"synthetic marker" in pending.result(timeout=20)
    configure(topology)
    other_allow = TenantFixtureAuthorization(
        other.database, other.token, other_org, "synthetic-publisher", 1
    )
    assert b"synthetic marker" in proxy(topology, other_org, other_allow).fetch(
        f"https://{HOST}/tooltip.html"
    )
    second_receipt = snapshot(topology)["calls"][0]
    assert second_receipt["received_monotonic"] - first_receipt["received_monotonic"] >= 4.9
    usage = Administration(other.database, other.token, other.settings).usage(other_org)
    assert usage.settled_resolution_units == 4 and usage.reserved_resolution_units == 0
    assert usage.source_resource_attempts == 1
    print(
        json.dumps(
            {
                "blocked_source_pool_progress": True,
                "actual_source_attempts": 2,
                "other_tenant_settled_units": 4,
                "private_export_completed": True,
            }
        ),
        flush=True,
    )


def test_actual_tenant_deletion_after_tls_response_never_releases_bytes(
    topology: Topology, scenario: Scenario
) -> None:
    from emailmonitor.lifecycle.models import DeletionRequest
    from emailmonitor.lifecycle.service import Lifecycle
    from test_progress_tenant import planned

    configure(topology)
    progress, job = planned(scenario, f"https://{HOST}/tooltip.html")
    org = scenario.organizations[0]
    authorization = TenantFixtureAuthorization(
        progress.database, progress.token, org, "synthetic-publisher", 1
    )
    service = Lifecycle(progress.database, progress.token, progress.settings)
    fenced: list[UUID] = []

    def delete_after_receipt() -> None:
        observed = snapshot(topology)
        assert len(observed["calls"]) == 1
        assert observed["calls"][0]["path"] == "/tooltip.html"
        receipt = service.stage(org, DeletionRequest(job_id=None, reason="privacy_request"))
        assert receipt.stage == "fenced"
        fenced.append(receipt.id)

    target = proxy(
        topology,
        org,
        authorization,
        resources=CompletionResources(authorization.resources, delete_after_receipt),
    )
    with pytest.raises(FetchDenied):
        target.fetch(f"https://{HOST}/tooltip.html")
    assert len(fenced) == 1 and len(snapshot(topology)["calls"]) == 1
    queries = len(snapshot(topology)["queries"])
    with pytest.raises(FetchDenied):
        proxy(topology, org, authorization).fetch(f"https://{HOST}/tooltip.html")
    assert len(snapshot(topology)["queries"]) == queries
    assert service.purge(org, fenced[0]).stage == "purged"
    print(
        json.dumps(
            {
                "tenant_deletion_before_release": True,
                "actual_received_responses": 1,
                "no_post_deletion_dns": True,
            }
        ),
        flush=True,
    )
