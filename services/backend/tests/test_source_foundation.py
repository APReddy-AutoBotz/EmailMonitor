"""Real PostgreSQL synthetic source-policy acceptance, with existing identity scenario."""

import time

import pytest
from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.config import Settings
from emailmonitor.identity.foundation import COOKIE, Foundation
from emailmonitor.organizations.database import Database
from emailmonitor.organizations.roles import Capability
from sqlalchemy import create_engine, text
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def policy_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "execution_mode": "fixture",
        "purpose": "academic_contact_research",
        "allowed_hosts": ["synthetic.publisher.example"],
        "allowed_operations": ["search", "fetch_html", "retain_excerpt", "export_contacts"],
        "permission_reference": "synthetic-fixtures-only",
        "credential_reference": None,
        "allowed_regions": ["test-only"],
        "robots_handling": "fixture_no_network",
        "limits": {
            "max_concurrent_requests": 1,
            "min_request_interval_seconds": 5,
            "max_articles_per_job": 500,
        },
        "retention": {"raw_hours": 24, "excerpt_days": 30, "contact_days": 90},
        "export_contacts_allowed": True,
        "valid_until": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400)),
    }
    body.update(overrides)
    return body


def source_path(scenario: Scenario, tenant: int = 0) -> str:
    return f"/api/v1/organizations/{scenario.organizations[tenant]}/sources/synthetic-publisher"


def test_source_policy_versions_approval_and_current_revocation(scenario: Scenario) -> None:
    with scenario.client() as client:
        csrf = scenario.login(client, "data_steward")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        catalog = client.get(f"/api/v1/organizations/{scenario.organizations[0]}/sources").json()
        assert len(catalog) == 1 and catalog[0]["execution_mode"] == "fixture"
        assert catalog[0]["support"]["extraction_implemented"] is False
        evaluation = {
            "expected_version": 1,
            "operation": "search",
            "host": "synthetic.publisher.example",
            "path": "/search-page-1.html",
            "execution_mode": "fixture",
        }
        assert client.post(path + "/evaluate", json=evaluation).status_code == 404
        response = client.post(
            path + "/policies",
            headers=headers,
            json={"expected_version": 0, "policy": policy_body()},
        )
        assert response.status_code == 201, response.text
        assert response.json()["state"] == "pending_review"
        assert response.json()["export_contacts_allowed"] is False
        assert client.post(path + "/evaluate", json=evaluation).json()["policy_authorized"] is False
        transition = {"expected_version": 1, "expected_revision": 1, "state": "approved"}
        response = client.post(path + "/policy-state", headers=headers, json=transition)
        assert response.status_code == 200, response.text
        assert response.json()["reviewed_by"] == str(scenario.identities["data_steward"])
        decision = client.post(path + "/evaluate", json=evaluation).json()
        assert decision["policy_authorized"] is True and decision["execution_available"] is False
        assert (
            client.post(path + "/evaluate", json={**evaluation, "path": "/unknown"}).json()[
                "policy_authorized"
            ]
            is False
        )
        assert (
            client.post(path + "/evaluate", json={**evaluation, "operation": "browser"}).json()[
                "policy_authorized"
            ]
            is False
        )
        assert (
            client.post(path + "/evaluate", json={**evaluation, "execution_mode": "live"}).json()[
                "policy_authorized"
            ]
            is False
        )
        assert (
            client.post(path + "/evaluate", json={**evaluation, "host": "evil.example"}).json()[
                "policy_authorized"
            ]
            is False
        )
        response = client.post(
            path + "/policy-state",
            headers=headers,
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200, response.text
        assert client.post(path + "/evaluate", json=evaluation).json()["policy_authorized"] is False
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 3, "state": "approved"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": policy_body()},
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 2, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        assert client.post(path + "/evaluate", json=evaluation).json()["policy_authorized"] is False
        assert (
            client.post(path + "/evaluate", json={**evaluation, "expected_version": 2}).json()[
                "policy_authorized"
            ]
            is True
        )
        assert len(client.get(path + "/policies").json()) == 2


@pytest.mark.parametrize("role", ["admin", "operator", "reviewer", "viewer"])
def test_source_policy_capability_denied(scenario: Scenario, role: str) -> None:
    with scenario.client() as client:
        csrf = scenario.login(client, role)
        assert (
            client.post(
                source_path(scenario) + "/policies",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"expected_version": 0, "policy": policy_body()},
            ).status_code
            == 404
        )


def test_source_policy_tenant_sql_and_permission_catalog(scenario: Scenario) -> None:
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        assert (
            client.post(
                source_path(scenario) + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
            ).status_code
            == 201
        )
        assert client.get(source_path(scenario, 1) + "/policies").status_code == 404
        assert (
            client.post(
                source_path(scenario, 1) + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
            ).status_code
            == 404
        )
        session = str(client.cookies[COOKIE])
        with scenario.foundation.database.tenant(
            session, scenario.organizations[0], Capability.READ_ORGANIZATION
        ) as (c, _):
            assert c.execute(
                text("SELECT DISTINCT organization_id FROM emailmonitor.source_policies")
            ).scalars().all() == [scenario.organizations[0]]
            for relation in ("source_policies", "source_policy_heads"):
                assert (
                    c.execute(
                        text(
                            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                            "WHERE oid=CAST(:table AS regclass)"
                        ),
                        {"table": "emailmonitor." + relation},
                    ).scalar_one()
                    is True
                )
            assert (
                c.execute(
                    text(
                        "SELECT has_table_privilege(current_user,"
                        "'emailmonitor.source_catalog','UPDATE')"
                    )
                ).scalar_one()
                is False
            )
        with scenario.foundation.database.transaction() as c:
            assert c.execute(text("SELECT * FROM emailmonitor.source_policies")).all() == []
        assert (
            client.post(
                source_path(scenario).replace("synthetic-publisher", "unknown") + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
            ).status_code
            == 404
        )


def test_source_policy_expiry_and_approval_requirements(scenario: Scenario) -> None:
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body(permission_reference=None)},
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": policy_body()},
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 2, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        # Deterministic application-time expiry check, without modifying immutable policy evidence.
        from datetime import UTC, datetime, timedelta
        from unittest.mock import patch

        import emailmonitor.sources.api as source_api

        future = datetime.now(UTC) + timedelta(days=2)

        with patch.object(source_api, "datetime") as clock:
            clock.now.return_value = future
            assert client.get(path + "/policies").json()[0]["state"] == "expired"
            assert (
                client.post(
                    path + "/evaluate",
                    json={
                        "expected_version": 2,
                        "operation": "search",
                        "host": "synthetic.publisher.example",
                        "path": "/search-page-1.html",
                        "execution_mode": "fixture",
                    },
                ).json()["policy_authorized"]
                is False
            )


def test_source_policy_csrf_suspension_and_version_race(scenario: Scenario) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    separate = Database(
        scenario.foundation.database.engine.url.render_as_string(hide_password=False)
    )
    separate_client = APIClient(
        create_app(
            Settings(environment="test", identity_stub=True),
            Foundation(separate, scenario.foundation.provider, scenario.foundation.authentication),
        ),
        base_url=ORIGIN,
    )
    with scenario.client() as owner, separate_client as steward:
        owner_csrf = scenario.login(owner, "owner")
        steward_csrf = scenario.login(steward, "data_steward")
        path = source_path(scenario)
        request = {"expected_version": 0, "policy": policy_body()}
        assert owner.post(path + "/policies", json=request).status_code == 403
        gate = Barrier(2)

        def propose(client: APIClient, csrf: str) -> int:
            gate.wait(timeout=5)
            return client.post(
                path + "/policies", json=request, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [
                executor.submit(propose, owner, owner_csrf),
                executor.submit(propose, steward, steward_csrf),
            ]
            assert sorted(response.result(timeout=10) for response in responses) == [201, 409]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": owner_csrf}
        assert (
            owner.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        assert (
            owner.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 2, "state": "suspended"},
            ).status_code
            == 200
        )
        assert (
            owner.post(
                path + "/evaluate",
                json={
                    "expected_version": 1,
                    "operation": "export_contacts",
                    "host": "synthetic.publisher.example",
                    "path": "/search-page-1.html",
                    "execution_mode": "fixture",
                },
            ).json()["policy_authorized"]
            is False
        )
        assert owner.get(path + "/policies").json()[0]["export_contacts_allowed"] is False
    separate.engine.dispose()


def test_source_policy_contract_catalog_fixture_parity(scenario: Scenario) -> None:
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "contracts/source-policy.schema.json").read_text())
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        response = client.post(
            path + "/policies",
            headers=headers,
            json={"expected_version": 0, "policy": policy_body()},
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(response.json())
        response = client.post(
            path + "/policy-state",
            headers=headers,
            json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(response.json())
        catalog = client.get(f"/api/v1/organizations/{scenario.organizations[0]}/sources").json()[0]
        assert set(catalog["support"]["fixture_routes"]) == {
            "/" + path.name for path in (root / "fixtures/html").glob("*.html")
        }
        assert "credential" not in json.dumps(catalog)


def test_source_platform_disable_cannot_be_overridden(scenario: Scenario) -> None:
    admin = create_engine(scenario.admin_url)
    try:
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
            with admin.begin() as c:
                c.execute(
                    text(
                        "UPDATE emailmonitor.source_catalog SET enabled=false "
                        "WHERE source_id='synthetic-publisher'"
                    )
                )
            assert (
                client.post(
                    path + "/evaluate",
                    json={
                        "expected_version": 1,
                        "operation": "search",
                        "host": "synthetic.publisher.example",
                        "path": "/search-page-1.html",
                        "execution_mode": "fixture",
                    },
                ).json()["policy_authorized"]
                is False
            )
    finally:
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.source_catalog SET enabled=true "
                    "WHERE source_id='synthetic-publisher'"
                )
            )
        admin.dispose()
