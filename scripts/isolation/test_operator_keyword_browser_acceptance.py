"""Combined keyword demo owns a fresh module topology and one single-attempt guest."""

import os
from collections.abc import Iterator

import pytest
from api_client import APIClient
from emailmonitor.runtime.assembly import TestRuntimeConfig as RuntimeConfig
from emailmonitor.runtime.assembly import owned_test_runtime
from test_durable_jobs import SETTINGS
from test_operator_browser_acceptance import _browser_operator_journey
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from test_transport_acceptance import topology as topology
from transport_topology import Topology


@pytest.fixture(scope="module")
def keyword_browser_topology(topology: Topology) -> Iterator[Topology]:
    # Importing the module-scoped topology fixture gives this module its own
    # instance. Never reuse the direct-tooltip case's exited/attempted guest.
    topology.browser()
    yield topology


def test_actual_keyword_browser_operator_ui(
    keyword_browser_topology: Topology,
    scenario: Scenario,
) -> None:
    if os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true":
        pytest.fail("Required controlled operator acceptance marker missing")
    config = RuntimeConfig(
        settings=SETTINGS.model_copy(update={"identity_stub": True}),
        runtime_database_url=os.environ["EM_TEST_DATABASE_URL"],
        authentication_database_url=os.environ["EM_TEST_AUTH_DATABASE_URL"],
    )
    with owned_test_runtime(config, scenario.foundation.provider) as runtime:
        assert runtime.api_database is not scenario.foundation.database
        assert runtime.publisher_database is not runtime.api_database
        _browser_operator_journey(keyword_browser_topology, scenario, runtime, keyword=True)
    with APIClient(runtime.app, ORIGIN) as closed:
        assert closed.get("/healthz").status_code == 503
