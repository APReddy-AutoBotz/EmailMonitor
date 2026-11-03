"""Fixture diagnostics must not serialize credentials or private test material."""

from typing import cast
from uuid import UUID

from emailmonitor.identity.foundation import Foundation
from test_tenant_foundation import FixtureExchange, Scenario


def test_scenario_repr_omits_private_test_values() -> None:
    private = "fixture-private-key-marker"
    password = "fixture-database-password-marker"
    code = "fixture-authorization-code-marker"
    scenario = Scenario(
        foundation=cast(Foundation, object()),
        private_key=private,
        exchange=FixtureExchange(codes={code: ("token-marker", "challenge-marker")}),
        organizations=(UUID(int=1), UUID(int=2)),
        identities={},
        admin_url=f"postgresql://synthetic:{password}@127.0.0.1/synthetic",
    )
    rendered = repr(scenario)
    assert private not in rendered
    assert password not in rendered
    assert code not in rendered
    assert "token-marker" not in rendered
