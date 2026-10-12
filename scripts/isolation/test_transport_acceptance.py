"""Actual controlled-network acceptance; runs only after independent CI review."""

import json
import os
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from emailmonitor.fetching.fixture import HOSTS, TenantFixtureAuthorization
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.sources.policy import Operation
from run_browser_acceptance import conversation
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
) -> GatewayProxy:
    def scope(operation: Operation) -> PlanScope:
        return PlanScope(
            organization, "synthetic-publisher", 1, operation, HOSTS, time.monotonic() + 4.5, 2
        )

    def check(bound: PlanScope, url: SafeURL) -> None:
        assert (
            bound.organization == organization
            and bound.source == "synthetic-publisher"
            and bound.policy_version == 1
        )
        if callable(authorize):
            authorize(url, bound.operation)

    return GatewayProxy(topology.processes["gateway"], scope, check, family, ca)


@pytest.mark.parametrize("family", [4, 6])
def test_actual_dns_selected_literal_tls_family(topology: Topology, family: int) -> None:
    configure(topology)
    target = proxy(topology, UUID("11111111-1111-4111-8111-111111111111"), family=family)
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
    target = proxy(topology, UUID("11111111-1111-4111-8111-111111111111"))
    assert b"synthetic marker" in target.fetch(f"https://{HOST}/redirect.html")
    assert target.peers == [
        [ENDPOINTS["fixture-a"][0], 443, HOST],
        [ENDPOINTS["fixture-b"][0], 443, HOST],
    ]
    assert len(snapshot(topology)["queries"]) == 4
    assert len(snapshot(topology)["calls"]) == len(snapshot(topology, "fixture-b")["calls"]) == 1
    print(
        json.dumps({"case": "redirect_dns_selected_peer_change", "peers": target.peers}), flush=True
    )


@pytest.mark.parametrize("mode", ["mixed", "private"])
def test_actual_dns_whole_snapshot_denies_before_tcp(topology: Topology, mode: str) -> None:
    configure(topology, mode)
    with pytest.raises(FetchDenied):
        proxy(topology, UUID("11111111-1111-4111-8111-111111111111")).fetch(
            f"https://{HOST}/tooltip.html"
        )
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2


@pytest.mark.parametrize("path", ["forbidden.html", "off-domain.html", "large.html"])
def test_actual_http_failure_no_retry_or_escape(topology: Topology, path: str) -> None:
    configure(topology)
    with pytest.raises(FetchDenied):
        proxy(topology, UUID("11111111-1111-4111-8111-111111111111")).fetch(
            f"https://{HOST}/{path}"
        )
    assert len(snapshot(topology)["calls"]) == 1
    assert len(snapshot(topology)["queries"]) == 2


def test_actual_untrusted_tls_certificate_is_not_released(topology: Topology) -> None:
    configure(topology)
    with pytest.raises(FetchDenied):
        proxy(topology, UUID("11111111-1111-4111-8111-111111111111"), ca="untrusted").fetch(
            f"https://{HOST}/tooltip.html"
        )
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2


def test_actual_trusted_ca_wrong_hostname_is_not_released(topology: Topology) -> None:
    configure(topology, "wrong_name")
    with pytest.raises(FetchDenied):
        proxy(topology, UUID("11111111-1111-4111-8111-111111111111")).fetch(
            f"https://{HOST}/tooltip.html"
        )
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2


def test_actual_rebinding_cannot_re_resolve_a_selected_socket(topology: Topology) -> None:
    configure(topology, "rebinding")
    target = proxy(topology, UUID("11111111-1111-4111-8111-111111111111"))
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
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        body = policy_body(
            allowed_operations=["fetch_html", "browser", "retain_excerpt", "export_contacts"]
        )
        assert (
            client.post(
                path + "/policies", headers=headers, json={"expected_version": 0, "policy": body}
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
        token = str(client.cookies[COOKIE])
        allow = TenantFixtureAuthorization(
            scenario.foundation.database, token, scenario.organizations[0], "synthetic-publisher", 1
        )
        target = proxy(topology, scenario.organizations[0], allow)
        mediator = BrowserProxyMediator(target)
        evidence = conversation(browser, mediator)
        actual_browser_peers = list(target.peers)
        observations = snapshot(topology)
        assert len(observations["calls"]) == 2 and len(observations["queries"]) == 4
        assert all(
            call["sni"] == HOST and set(call["headers"]) == {"Host", "Accept", "Connection"}
            for call in observations["calls"]
        )
        assert mediator.accepted == 2 and mediator.denied >= 7
        denied = TenantFixtureAuthorization(
            scenario.foundation.database, token, scenario.organizations[1], "synthetic-publisher", 1
        )
        with pytest.raises(FetchDenied):
            proxy(topology, scenario.organizations[1], denied).fetch(
                f"https://{HOST}/tooltip.html", Operation.BROWSER
            )
        assert len(snapshot(topology)["calls"]) == 2
        assert len(snapshot(topology)["queries"]) == 4
        stale = TenantFixtureAuthorization(
            scenario.foundation.database, token, scenario.organizations[0], "synthetic-publisher", 2
        )
        with pytest.raises(FetchDenied):
            proxy(topology, scenario.organizations[0], stale).fetch(
                f"https://{HOST}/tooltip.html", Operation.BROWSER
            )
        assert len(snapshot(topology)["queries"]) == 4
        callback_count = [0]

        def revoke_before_release(url: SafeURL, operation: Operation) -> None:
            callback_count[0] += 1
            # Host precheck + guest before-DNS/after-DNS/before-connect/after-TLS:
            # the sixth current-policy callback is the gateway's byte release.
            if callback_count[0] == 6:
                assert (
                    client.post(
                        path + "/policy-state",
                        headers=headers,
                        json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                    ).status_code
                    == 200
                )
            allow(url, operation)

        inflight = proxy(topology, scenario.organizations[0], revoke_before_release)
        with pytest.raises(FetchDenied):
            inflight.fetch(f"https://{HOST}/tooltip.html", Operation.BROWSER)
        assert callback_count[0] == 6
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
