from collections.abc import Iterator
from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import (
    ByteResponse,
    FixtureByteTransport,
    FixtureGateway,
    TenantFixtureAuthorization,
)
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.identity.foundation import COOKIE
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

URL = "https://synthetic.publisher.example/article-a.html"
SETTINGS = Settings(environment="test", fixture_mode=True)


def test_gateway_real_tenant_policy_and_stale_version(scenario: Scenario) -> None:
    payload = (Path(__file__).resolve().parents[3] / "fixtures/html/article-a.html").read_bytes()
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
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
        transport = FixtureByteTransport(SETTINGS, {URL: ByteResponse(200, (payload,))})
        authorize = TenantFixtureAuthorization(
            scenario.foundation.database, token, scenario.organizations[0], "synthetic-publisher", 1
        )
        assert FixtureGateway(SETTINGS, transport, authorize).fetch(URL) == payload
        for organization, version in (
            (scenario.organizations[1], 1),
            (scenario.organizations[0], 2),
        ):
            denied = TenantFixtureAuthorization(
                scenario.foundation.database, token, organization, "synthetic-publisher", version
            )
            with pytest.raises(FetchDenied):
                FixtureGateway(SETTINGS, transport, denied).fetch(URL)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": policy_body()},
            ).status_code
            == 201
        )
        with pytest.raises(FetchDenied):
            FixtureGateway(SETTINGS, transport, authorize).fetch(URL)


def test_gateway_rechecks_real_revocation_before_releasing_bytes(scenario: Scenario) -> None:
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
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

        def chunks() -> Iterator[bytes]:
            yield b"fixture-first"
            assert (
                client.post(
                    path + "/policy-state",
                    headers=headers,
                    json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                ).status_code
                == 200
            )
            yield b"fixture-second"

        authorize = TenantFixtureAuthorization(
            scenario.foundation.database, token, scenario.organizations[0], "synthetic-publisher", 1
        )
        gateway = FixtureGateway(
            SETTINGS, FixtureByteTransport(SETTINGS, {URL: ByteResponse(200, chunks())}), authorize
        )
        with pytest.raises(FetchDenied):
            gateway.fetch(URL)


@pytest.mark.parametrize("role", ["viewer", "reviewer"])
def test_gateway_readonly_roles_cannot_acquire(scenario: Scenario, role: str) -> None:
    with scenario.client() as client:
        scenario.login(client, role)
        authorize = TenantFixtureAuthorization(
            scenario.foundation.database,
            str(client.cookies[COOKIE]),
            scenario.organizations[0],
            "synthetic-publisher",
            1,
        )
        with pytest.raises(FetchDenied):
            FixtureGateway(
                SETTINGS,
                FixtureByteTransport(SETTINGS, {URL: ByteResponse(200, (b"fixture",))}),
                authorize,
            ).fetch(URL)


def test_actual_tls_gateway_uses_current_tenant_policy(scenario: Scenario, tmp_path: Path) -> None:
    from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
    from test_tls_fixture import Response, server

    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
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
        authorize = TenantFixtureAuthorization(
            scenario.foundation.database, token, scenario.organizations[0], "synthetic-publisher", 1
        )
        with server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls):
            gateway = TLSFixtureGateway(SETTINGS, endpoint, authorize)
            assert gateway.fetch(URL) == b"<p>synthetic observation</p>"
            denied = TenantFixtureAuthorization(
                scenario.foundation.database,
                token,
                scenario.organizations[1],
                "synthetic-publisher",
                1,
            )
            with pytest.raises(FetchDenied):
                TLSFixtureGateway(SETTINGS, endpoint, denied).fetch(URL)
            assert len(calls) == 1
            assert (
                client.post(
                    path + "/policy-state",
                    headers=headers,
                    json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                ).status_code
                == 200
            )
            with pytest.raises(FetchDenied):
                gateway.fetch(URL)
            assert len(calls) == 1
