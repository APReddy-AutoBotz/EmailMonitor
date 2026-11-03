"""Actual existing PostgreSQL roles and authenticated owned runtime lifecycle."""

import os

import pytest
from api_client import APIClient
from emailmonitor.config import Settings
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.runtime.assembly import TestRuntimeConfig as RuntimeConfig
from emailmonitor.runtime.assembly import owned_test_runtime
from sqlalchemy import text
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def configuration() -> RuntimeConfig:
    return RuntimeConfig(
        settings=Settings(environment="test", fixture_mode=True, identity_stub=True),
        runtime_database_url=os.environ["EM_TEST_DATABASE_URL"],
        authentication_database_url=os.environ["EM_TEST_AUTH_DATABASE_URL"],
    )


def test_owned_runtime_real_identity_roles_pool_separation_and_revocation(
    scenario: Scenario,
) -> None:
    org, other = scenario.organizations
    with owned_test_runtime(configuration(), scenario.foundation.provider) as runtime:
        assert runtime.api_database.engine is not runtime.publisher_database.engine
        assert runtime.api_database.engine is not scenario.foundation.database.engine
        with APIClient(runtime.app, ORIGIN) as owner:
            csrf = scenario.login(owner, "owner")
            token = str(owner.cookies[COOKIE])
            assert owner.get(f"/api/v1/organizations/{org}").status_code == 200
            assert owner.get(f"/api/v1/organizations/{other}").status_code == 404
            # Both pool_size=1 pools can be checked out simultaneously. The
            # publisher shares current session authority, never an admin role.
            with runtime.api_database.transaction() as api_connection:
                with runtime.publisher_database.tenant(
                    token, org, Capability.READ_ORGANIZATION
                ) as (publisher_connection, _):
                    assert (
                        api_connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                        != publisher_connection.execute(
                            text("SELECT pg_backend_pid()")
                        ).scalar_one()
                    )
                    assert (
                        publisher_connection.execute(
                            text(
                                "SELECT has_function_privilege(current_user,"
                                "'emailmonitor.establish_session(text,text,text,text)','EXECUTE')"
                            )
                        ).scalar_one()
                        is False
                    )
            assert owner.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
            assert (
                owner.post(
                    "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
                ).status_code
                == 204
            )
            with pytest.raises(AuthorizationDenied):
                with runtime.publisher_database.tenant(token, org, Capability.READ_ORGANIZATION):
                    raise AssertionError("Revoked session admitted")
        with APIClient(runtime.app, ORIGIN) as second:
            scenario.login(second, "owner_b")
            assert second.get(f"/api/v1/organizations/{other}").status_code == 200
            assert second.get(f"/api/v1/organizations/{org}").status_code == 404
    with APIClient(runtime.app, ORIGIN) as closed:
        assert closed.get("/healthz").status_code == 503
        assert closed.get(f"/api/v1/organizations/{org}").status_code == 503
    # Borrowed identity provider and original Scenario remain caller-owned.
    with scenario.client() as caller:
        scenario.login(caller, "owner")
        assert caller.get(f"/api/v1/organizations/{org}").status_code == 200


@pytest.mark.parametrize("role", ["runtime", "authentication", "swapped"])
def test_owned_runtime_rejects_actual_privileged_database_login(
    scenario: Scenario, role: str
) -> None:
    config = configuration()
    unsafe = RuntimeConfig(
        settings=config.settings,
        runtime_database_url=scenario.admin_url
        if role == "runtime"
        else config.authentication_database_url
        if role == "swapped"
        else config.runtime_database_url,
        authentication_database_url=scenario.admin_url
        if role == "authentication"
        else config.runtime_database_url
        if role == "swapped"
        else config.authentication_database_url,
    )
    with pytest.raises(RuntimeError) as error:
        with owned_test_runtime(unsafe, scenario.foundation.provider):
            raise AssertionError("Privileged login admitted")
    assert scenario.admin_url not in str(error.value)
    with scenario.client() as caller:
        scenario.login(caller, "owner")
        assert caller.get(f"/api/v1/organizations/{scenario.organizations[0]}").status_code == 200
