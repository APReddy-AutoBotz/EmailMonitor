"""Actual synthetic PostgreSQL/ASGI operator boundaries; no local service substitute."""

from uuid import UUID, uuid4

import pytest
from emailmonitor.identity.foundation import COOKIE, CSRF_COOKIE
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_results_tenant import options, prepared
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def test_real_session_bootstrap_cookie_reload_logout_and_origin(scenario: Scenario) -> None:
    with scenario.client() as client:
        assert (
            client.get("/api/v1/auth/session", headers={"X-EmailMonitor-UI": "session"}).status_code
            == 401
        )
        nonce = scenario.login(client, "owner")
        cookie = next(value for value in client.cookies.jar if value.name == CSRF_COOKIE)
        assert cookie.secure and cookie.path == "/" and cookie.has_nonstandard_attr("HttpOnly")
        assert client.get("/api/v1/auth/session").status_code == 403
        assert (
            client.get(
                "/api/v1/auth/session",
                headers={"X-EmailMonitor-UI": "session", "Origin": "https://other.example"},
            ).status_code
            == 403
        )
        for _ in range(2):
            result = client.get(
                "/api/v1/auth/session", headers={"X-EmailMonitor-UI": "session", "Origin": ORIGIN}
            )
            assert result.status_code == 200, result.text
            assert result.json()["csrf_token"] == nonce
            assert result.json()["production_enabled"] is False
            assert "organization.lifecycle" in result.json()["memberships"][0]["capabilities"]
        client.cookies.set(CSRF_COOKIE, "forged-nonce", domain="app.example.test", path="/")
        assert (
            client.get("/api/v1/auth/session", headers={"X-EmailMonitor-UI": "session"}).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": nonce}
            ).status_code
            == 204
        )
        assert (
            client.get("/api/v1/auth/session", headers={"X-EmailMonitor-UI": "session"}).status_code
            == 401
        )


def test_real_operator_profile_revision_role_usage_and_audit(scenario: Scenario) -> None:
    org = scenario.organizations[0]
    path = f"/api/v1/organizations/{org}"
    with scenario.client() as owner, scenario.client() as admin, scenario.client() as viewer:
        nonce = scenario.login(owner, "owner")
        admin_nonce = scenario.login(admin, "admin")
        scenario.login(viewer, "viewer")
        original = owner.get(path).json()
        body = {
            "display_name": "Renamed synthetic workspace",
            "timezone": "Asia/Kolkata",
            "expected_revision": original["row_version"],
        }
        assert (
            admin.patch(
                path + "/profile",
                json=body,
                headers={"Origin": ORIGIN, "X-CSRF-Token": admin_nonce},
            ).status_code
            == 404
        )
        result = owner.patch(
            path + "/profile", json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": nonce}
        )
        assert result.status_code == 200, result.text
        assert result.json()["row_version"] == original["row_version"] + 1
        assert (
            owner.patch(
                path + "/profile", json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": nonce}
            ).status_code
            == 409
        )
        usage = viewer.get(path + "/usage")
        assert usage.status_code == 200 and usage.json()["cost"] is None
        assert not usage.json()["billing_implemented"]
        assert viewer.get(path + "/audit").status_code == 404
        history = owner.get(path + "/audit?limit=1")
        assert history.status_code == 200 and len(history.json()["items"]) == 1
        assert owner.get(path + f"/audit?cursor={uuid4()}").status_code == 404


def test_real_export_preview_current_scope_optional_fields_and_snapshot(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    request = options(job, optional_contact_fields=[])
    preview = results.preview(org, request)
    assert preview.contacts == len(results.contacts(org, Filters(job_id=job)).items)
    assert preview.optional_contact_fields == () and preview.counts_may_change
    assert "unaccepted_excluded_by_default" in preview.excluded_reasons
    state = results.create(org, request, str(uuid4()))
    row = next(row for row in results.pending(org) if row["export_id"] == state.id)
    claimed = results.claim(org, state.id, UUID(str(row["event_id"])), int(str(row["generation"])))
    assert claimed is not None and claimed.snapshot.optional_contact_fields == ()
    with pytest.raises(AuthorizationDenied):
        results.preview(uuid4(), request)


@pytest.mark.parametrize(
    "role", ["owner", "admin", "data_steward", "operator", "reviewer", "viewer"]
)
def test_real_operator_metadata_uses_current_role_and_cross_tenant_concealment(
    scenario: Scenario, role: str
) -> None:
    with scenario.client() as client:
        scenario.login(client, role)
        session = client.get("/api/v1/auth/session", headers={"X-EmailMonitor-UI": "session"})
        assert session.status_code == 200
        member = session.json()["memberships"][0]
        assert member["role"] == role
        org, other = scenario.organizations
        assert client.get(f"/api/v1/organizations/{org}/usage").status_code == 200
        assert client.get(f"/api/v1/organizations/{other}/usage").status_code == 404
        assert client.get(f"/api/v1/organizations/{other}/audit").status_code == 404
        expected = 200 if role in {"owner", "admin"} else 404
        assert client.get(f"/api/v1/organizations/{org}/audit").status_code == expected
        assert ("organization.lifecycle" in member["capabilities"]) == (role == "owner")


def test_real_preview_private_helper_and_current_role_source_fences(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    with results.database.tenant(results.token, org, Capability.EXPORT_RESULTS) as (c, _):
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user,"
                "'emailmonitor.export_request_validate(jsonb)','EXECUTE')"
            )
        ).scalar_one()
        assert c.execute(
            text(
                "SELECT has_function_privilege(current_user,"
                "'emailmonitor.exports_preview(uuid,jsonb)','EXECUTE')"
            )
        ).scalar_one()
    with scenario.client() as operator, scenario.client() as owner:
        scenario.login(operator, "operator")
        token = next(value.value for value in operator.cookies.jar if value.name == COOKIE)
        with pytest.raises(AuthorizationDenied):
            Results(results.database, token, SETTINGS).preview(org, options(job))
        nonce = scenario.login(owner, "owner")
        response = owner.post(
            source_path(scenario) + "/policy-state",
            headers={"Origin": ORIGIN, "X-CSRF-Token": nonce},
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200, response.text
    with pytest.raises(AuthorizationDenied):
        results.preview(org, options(job))
