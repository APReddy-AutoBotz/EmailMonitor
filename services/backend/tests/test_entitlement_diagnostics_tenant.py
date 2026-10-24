"""Actual false-return reasons remain false; temporary SQL restores exactly."""

import pytest
from emailmonitor.administration.models import ConfigurationUpdate
from emailmonitor.administration.service import Administration
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.entitlement_diagnostics import PREFIX, STATEMENT, EntitlementDiagnostics
from emailmonitor.organizations.roles import Capability
from entitlement_sql_diagnostic import definition, entitlement_diagnostic, ownership
from sqlalchemy import create_engine, text
from test_durable_jobs import SETTINGS
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_actual_entitlement_diagnostic_preserves_denials_and_restores(scenario: Scenario) -> None:
    engine = create_engine(scenario.admin_url, hide_parameters=True)
    original, privileges = definition(engine), ownership(engine)
    output: list[str] = []
    EntitlementDiagnostics(output.append).connect(scenario.foundation.database.engine)
    org = scenario.organizations[0]
    try:
        with scenario.client() as client:
            scenario.login(client, "owner")
            token = str(client.cookies[COOKIE])
        with entitlement_diagnostic(engine):
            assert ownership(engine) == privileges

            def invoke(operation: str) -> bool:
                with scenario.foundation.database.tenant(token, org, Capability.ACQUIRE_SOURCE) as (
                    c,
                    _,
                ):
                    value: bool = c.execute(
                        text(STATEMENT), {"org": org, "operation": operation, "job": None}
                    ).scalar_one()
                    return value

            assert invoke("fetch_html") is True
            assert output[-1] == PREFIX + "allowed\n"
            assert invoke("invalid") is False
            assert output[-1] == PREFIX + "authority_denied\n"
            with engine.begin() as holder:
                holder.execute(
                    text(
                        "SELECT 1 FROM emailmonitor.organizations WHERE id=:org FOR UPDATE NOWAIT"
                    ),
                    {"org": org},
                )
                assert invoke("fetch_html") is False
                assert output[-1] == PREFIX + "lock_refused\n"
            assert invoke("fetch_html") is True
            assert output[-1] == PREFIX + "allowed\n"
            administration = Administration(scenario.foundation.database, token, SETTINGS)
            current = administration.read(org)
            administration.update(
                org,
                ConfigurationUpdate(
                    expected_revision=current.revision,
                    entitlements=current.entitlements.model_copy(update={"max_parallel_parse": 0}),
                    branding=current.branding,
                ),
            )
            assert invoke("fetch_html") is False
            assert output[-1] == PREFIX + "authority_denied\n"
        assert definition(engine) == original and ownership(engine) == privileges
        with pytest.raises(RuntimeError, match="owned failure"):
            with entitlement_diagnostic(engine):
                raise RuntimeError("owned failure")
        assert definition(engine) == original and ownership(engine) == privileges
    finally:
        engine.dispose()
