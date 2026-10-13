"""Owned context and transaction-local settings, without a database or sockets."""

from typing import cast
from uuid import uuid4

import pytest
from emailmonitor.progress.binding import CURRENT, Lease, apply, bound
from sqlalchemy import Connection


class Capture:
    def __init__(self) -> None:
        self.params: list[dict[str, str]] = []

    def execute(self, query: object, parameters: dict[str, str]) -> None:
        assert "set_config" in str(query) and ",true)" in str(query)
        assert "organization_id" not in str(query) and "session_hash" not in str(query)
        self.params.append(parameters)


def lease() -> Lease:
    return Lease(uuid4(), uuid4(), uuid4(), uuid4(), 1, 1)


def test_transaction_settings_clear_and_restore_owned_context() -> None:
    capture = Capture()
    first, second = lease(), lease()
    apply(cast(Connection, capture), first.organization)
    assert set(capture.params[-1].values()) == {""}
    with bound(first):
        apply(cast(Connection, capture), first.organization)
        assert capture.params[-1]["token"] == str(first.token)
        with bound(second):
            assert CURRENT.get() is second
        assert CURRENT.get() is first
    assert CURRENT.get() is None
    apply(cast(Connection, capture), first.organization)
    assert set(capture.params[-1].values()) == {""}


def test_exception_clears_context_and_cross_tenant_apply_refuses() -> None:
    scope = lease()
    with pytest.raises(ValueError, match="tenant"):
        with bound(scope):
            apply(cast(Connection, Capture()), uuid4())
    assert CURRENT.get() is None


@pytest.mark.parametrize("generation", [0, -1, True])
def test_invalid_work_generation_refuses(generation: int) -> None:
    scope = lease()
    malformed = Lease(scope.organization, scope.job, scope.item, scope.token, generation, 1)
    with pytest.raises(ValueError):
        with bound(malformed):
            pytest.fail("Invalid work scope was installed")
