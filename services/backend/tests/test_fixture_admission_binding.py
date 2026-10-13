"""Pure owned-context tests; SQL active/current/expiry proof remains actual CI."""

from typing import cast
from uuid import uuid4

import pytest
from emailmonitor.administration.binding import CURRENT, FixtureLease, apply, bound, fence
from emailmonitor.organizations.database import AuthorizationDenied
from sqlalchemy import Connection


class Recording:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[dict[str, object]] = []

    def execute(self, statement: object, parameters: dict[str, object]) -> "Recording":
        self.calls.append(parameters)
        return self

    def scalar_one(self) -> bool:
        return self.allowed


def lease() -> FixtureLease:
    return FixtureLease(
        uuid4(), uuid4(), "https://synthetic.publisher.example/article-a.html", uuid4(), uuid4()
    )


def test_owned_binding_applies_exact_scope_and_resets() -> None:
    owned = lease()
    recording = Recording()
    assert CURRENT.get() is None
    with bound(owned):
        apply(cast(Connection, recording), owned.organization)
        assert recording.calls[-1] == {
            "job": str(owned.job),
            "url": owned.url,
            "reference": str(owned.reference),
            "nonce": str(owned.nonce),
        }
        fence(cast(Connection, recording), owned.organization, owned.job, owned.url)
        with pytest.raises(ValueError):
            apply(cast(Connection, recording), uuid4())
    assert CURRENT.get() is None


@pytest.mark.parametrize("change", ["organization", "job", "url", "denied"])
def test_current_lease_cannot_authorize_other_scope_or_refused_fence(change: str) -> None:
    owned = lease()
    recording = Recording(allowed=change != "denied")
    with bound(owned), pytest.raises(AuthorizationDenied):
        fence(
            cast(Connection, recording),
            uuid4() if change == "organization" else owned.organization,
            uuid4() if change == "job" else owned.job,
            "https://synthetic.publisher.example/article-b.html" if change == "url" else owned.url,
        )
    assert CURRENT.get() is None


def test_nested_binding_restores_original_and_error_does_not_leak() -> None:
    first, second = lease(), lease()
    with bound(first):
        with pytest.raises(RuntimeError):
            with bound(second):
                assert CURRENT.get() is second
                raise RuntimeError("Synthetic failure")
        assert CURRENT.get() is first
    assert CURRENT.get() is None
