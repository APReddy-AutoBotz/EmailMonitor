"""Required actual runtime PostgreSQL/ASGI configuration fences, CI only."""

from uuid import uuid4

from api_client import APIClient
from emailmonitor.administration.models import Branding, ConfigurationUpdate, Entitlements
from emailmonitor.administration.service import Administration
from emailmonitor.api import create_app
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.organizations.roles import Capability
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def _client(s: Scenario) -> APIClient:
    return APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), s.foundation),
        base_url=ORIGIN,
    )


def _token(s: Scenario, role: str) -> str:
    with _client(s) as client:
        s.login(client, role)
        return str(client.cookies[COOKIE])


def test_real_configuration_owner_revision_current_role_and_csrf(scenario: Scenario) -> None:
    organization = scenario.organizations[0]
    path = f"/api/v1/organizations/{organization}/configuration"
    with _client(scenario) as owner, _client(scenario) as admin, _client(scenario) as viewer:
        nonce = scenario.login(owner, "owner")
        admin_nonce = scenario.login(admin, "admin")
        scenario.login(viewer, "viewer")
        original = owner.get(path)
        assert original.status_code == 200, original.text
        data = original.json()
        assert data["deployment_mode"] == "synthetic_offline"
        assert not data["billing_implemented"] and not data["exceptional_support_grants_available"]
        assert viewer.get(path).json() == data
        body = {
            "expected_revision": data["revision"],
            "entitlements": data["entitlements"],
            "branding": {
                "accent_color": "#123456",
                "label": "Reviewed authored workspace",
                "logo_reference": None,
            },
        }
        assert owner.patch(path, json=body).status_code == 403
        assert (
            admin.patch(
                path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": admin_nonce}
            ).status_code
            == 404
        )
        changed = owner.patch(path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": nonce})
        assert changed.status_code == 200, changed.text
        assert changed.json()["revision"] == data["revision"] + 1
        assert changed.json()["support_reference"] == data["support_reference"]
        assert changed.json()["branding"]["accent_color"] == "#123456"
        assert (
            owner.patch(
                path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": nonce}
            ).status_code
            == 409
        )
        body["expected_revision"] += 1
        body["entitlements"]["max_running_jobs"] = 3
        assert (
            owner.patch(
                path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": nonce}
            ).status_code
            == 422
        )


def test_real_configuration_cross_tenant_and_private_infrastructure_permissions(
    scenario: Scenario,
) -> None:
    with _client(scenario) as client:
        scenario.login(client, "owner")
        own = f"/api/v1/organizations/{scenario.organizations[0]}/configuration"
        assert client.get(own).status_code == 200
        for organization in (scenario.organizations[1], uuid4()):
            unavailable = client.get(f"/api/v1/organizations/{organization}/configuration")
            assert unavailable.status_code == 404 and unavailable.json() == {
                "detail": "Resource unavailable"
            }
    with scenario.foundation.database.tenant(
        _token(scenario, "owner"), scenario.organizations[0], Capability.READ_ORGANIZATION
    ) as (connection, _):
        assert (
            connection.execute(
                text(
                    """SELECT count(*) FROM emailmonitor.tenant_configuration
WHERE organization_id=:other"""
                ),
                {"other": scenario.organizations[1]},
            ).scalar_one()
            == 0
        )
        assert not connection.execute(
            text(
                """SELECT has_table_privilege(current_user,
'emailmonitor.tenant_configuration','UPDATE')"""
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                """SELECT has_function_privilege(current_user,
'emailmonitor.administration_validate(jsonb)','EXECUTE')"""
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                """SELECT has_function_privilege(current_user,
'emailmonitor.administration_default()','EXECUTE')"""
            )
        ).scalar_one()


def test_real_configuration_update_audits_numeric_metadata_without_label_content(
    scenario: Scenario,
) -> None:
    organization = scenario.organizations[0]
    admin = Administration(scenario.foundation.database, _token(scenario, "owner"), SETTINGS)
    before = admin.read(organization)
    after = admin.update(
        organization,
        ConfigurationUpdate(
            expected_revision=before.revision,
            entitlements=Entitlements(monthly_resolution_units=100),
            branding=Branding(label="Synthetic private label"),
        ),
    )
    assert after.entitlements.monthly_resolution_units == 100
    with scenario.foundation.database.tenant(
        _token(scenario, "owner"), organization, Capability.READ_ORGANIZATION
    ) as (connection, _):
        row = (
            connection.execute(
                text("SELECT * FROM emailmonitor.configuration_events WHERE organization_id=:org"),
                {"org": organization},
            )
            .mappings()
            .one()
        )
        assert row["old_revision"] == before.revision and row["new_revision"] == after.revision
        assert (
            row["new_limits"]["monthly_resolution_units"] == 100 and row["branding_changed"] is True
        )
        assert "Synthetic private label" not in str(dict(row))
        assert (
            connection.execute(
                text(
                    """SELECT count(*) FROM emailmonitor.audit_events WHERE organization_id=:org
AND action='organization.configuration_updated'"""
                ),
                {"org": organization},
            ).scalar_one()
            == 1
        )


def test_real_configuration_reloads_after_reduced_quota_and_new_reader(scenario: Scenario) -> None:
    organization = scenario.organizations[0]
    first = Administration(scenario.foundation.database, _token(scenario, "owner"), SETTINGS)
    before = first.read(organization)
    first.update(
        organization,
        ConfigurationUpdate(
            expected_revision=before.revision,
            entitlements=Entitlements(monthly_resolution_units=0, exports_enabled=False),
            branding=before.branding,
        ),
    )
    fresh = Administration(scenario.foundation.database, _token(scenario, "viewer"), SETTINGS).read(
        organization
    )
    assert fresh.revision == before.revision + 1
    assert (
        fresh.entitlements.monthly_resolution_units == 0 and not fresh.entitlements.exports_enabled
    )


def test_real_runtime_cannot_mutate_or_read_shared_admission_metadata(scenario: Scenario) -> None:
    org = scenario.organizations[0]
    with scenario.foundation.database.tenant(
        _token(scenario, "owner"), org, Capability.READ_ORGANIZATION
    ) as (connection, _):
        for table in (
            "admission_mutex",
            "admission_pools",
            "source_resource_buckets",
            "export_entitlements",
        ):
            assert not connection.execute(
                text("SELECT has_table_privilege(current_user,:table,'SELECT')"),
                {"table": f"emailmonitor.{table}"},
            ).scalar_one()
        for table in (
            "tenant_configuration",
            "admission_requests",
            "resolution_accounts",
            "source_resource_requests",
            "tenant_source_buckets",
        ):
            assert not connection.execute(
                text("SELECT has_table_privilege(current_user,:table,'UPDATE')"),
                {"table": f"emailmonitor.{table}"},
            ).scalar_one()
        for function in (
            "admission_cleanup()",
            "admission_try(uuid,uuid,uuid,text,bigint,uuid,integer)",
            "resolution_reserve(uuid,uuid,uuid)",
            "source_resource_current(uuid,uuid)",
        ):
            assert not connection.execute(
                text("SELECT has_function_privilege(current_user,:function,'EXECUTE')"),
                {"function": f"emailmonitor.{function}"},
            ).scalar_one()
