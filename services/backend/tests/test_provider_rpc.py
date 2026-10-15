"""Closed owned-pipe binding/poisoning regressions, no network or admission grant."""

import base64
import hashlib
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from emailmonitor.fetching.safety import FetchDenied
from test_provider_transport import BODY, assembly
from transport_manifest import ENDPOINTS
from transport_provider import ProviderProxy
from transport_rpc import OwnedProcess


class Process:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = iter(frames)
        self.sent: list[dict[str, object]] = []
        self.poisoned = False

    def send(self, value: dict[str, object], deadline: float) -> None:
        self.sent.append(value)

    def receive(self, deadline: float) -> dict[str, Any]:
        return next(self.frames)


@pytest.mark.parametrize(
    "change", ["none", "binding", "boolean", "request", "digest", "peers", "extra"]
)
def test_provider_result_checked_against_original_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _, boundary, _, _, _, _, _ = assembly(tmp_path, monkeypatch)
    frame: dict[str, Any] = {
        "kind": "provider_result",
        "status": "ok",
        "request": boundary.request.model_dump(mode="json"),
        "binding": boundary.binding.model_dump(mode="json"),
        "body": base64.b64encode(BODY).decode(),
        "digest": hashlib.sha256(BODY).hexdigest(),
        "peers": [[ENDPOINTS["fixture-a"][0], 443, "api.elsevier.com"]],
    }
    if change == "binding":
        frame["binding"]["lease"] = str(UUID(int=99))
    elif change == "boolean":
        frame["binding"]["policy_revision"] = True
    elif change == "request":
        frame["request"]["search"]["query"] = "another query"
    elif change == "digest":
        frame["digest"] = "0" * 64
    elif change == "peers":
        frame["peers"] = [["127.0.0.1", 443, "api.elsevier.com"]]
    elif change == "extra":
        frame["extra"] = "unrequested"
    process = Process([frame])
    target = ProviderProxy(cast(OwnedProcess, process))
    if change == "none":
        assert target.acquire(boundary).body == BODY
        assert not process.poisoned
    else:
        with pytest.raises(RuntimeError):
            target.acquire(boundary)
        assert process.poisoned


@pytest.mark.parametrize("revision", [True, 2])
def test_malformed_current_callback_poisoned_without_authority_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision: Any
) -> None:
    _, boundary, _, _, _, _, _ = assembly(tmp_path, monkeypatch)
    copied = boundary.binding.model_dump(mode="json")
    copied["policy_revision"] = revision
    process = Process([{"kind": "provider_current", "binding": copied}])
    with pytest.raises(RuntimeError):
        ProviderProxy(cast(OwnedProcess, process)).acquire(boundary)
    assert process.poisoned and len(process.sent) == 1


def test_well_formed_denial_is_terminal_without_channel_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, boundary, _, _, _, _, _ = assembly(tmp_path, monkeypatch)
    process = Process([{"kind": "provider_result", "status": "denied"}])
    with pytest.raises(FetchDenied):
        ProviderProxy(cast(OwnedProcess, process)).acquire(boundary)
    assert not process.poisoned


@pytest.mark.parametrize("failure", ["protocol", "finish"])
def test_resource_cleanup_failure_never_reopens_uncertain_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from emailmonitor.fetching.safety import SafeURL
    from emailmonitor.sources.policy import Operation
    from transport_gateway import scope_fields

    _, boundary, _, _, _, _, _ = assembly(tmp_path, monkeypatch)
    scope = scope_fields(boundary.planner.scope)
    identity = str(UUID(int=80))
    frames: list[dict[str, Any]] = [
        {"kind": "resource_acquire", "id": identity, "scope": scope, "url": boundary.request.url}
    ]
    frames.append(
        {
            "kind": "resource_finish",
            "id": identity,
            "scope": scope,
            "status": 200,
            "retry_after": "",
        }
        if failure == "finish"
        else {"kind": "unknown"}
    )
    process = Process(frames)

    class Resources:
        calls = 0

        def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
            return identity

        def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
            assert ticket == identity
            self.calls += 1
            raise RuntimeError("Owned SQL cleanup refused")

    resources = Resources()
    with pytest.raises(
        RuntimeError, match="SQL cleanup" if failure == "finish" else "Unexpected provider"
    ):
        ProviderProxy(cast(OwnedProcess, process)).acquire(boundary, resources=resources)
    assert process.poisoned and resources.calls == 1


@pytest.mark.parametrize("mode", ["missing", "duplicate", "valid"])
def test_sql_resource_mode_requires_one_owned_completed_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from emailmonitor.fetching.safety import SafeURL
    from emailmonitor.sources.policy import Operation
    from transport_gateway import scope_fields

    _, boundary, _, _, _, _, _ = assembly(tmp_path, monkeypatch)
    scope = scope_fields(boundary.planner.scope)
    identity = str(UUID(int=81))
    acquire: dict[str, Any] = {
        "kind": "resource_acquire",
        "id": identity,
        "scope": scope,
        "url": boundary.request.url,
    }
    finish: dict[str, Any] = {
        "kind": "resource_finish",
        "id": identity,
        "scope": scope,
        "status": 200,
        "retry_after": "",
    }
    result: dict[str, Any] = {
        "kind": "provider_result",
        "status": "ok",
        "request": boundary.request.model_dump(mode="json"),
        "binding": boundary.binding.model_dump(mode="json"),
        "body": base64.b64encode(BODY).decode(),
        "digest": hashlib.sha256(BODY).hexdigest(),
        "peers": [[ENDPOINTS["fixture-a"][0], 443, "api.elsevier.com"]],
    }
    frames: list[dict[str, Any]] = (
        [result]
        if mode == "missing"
        else [acquire, finish, result]
        if mode == "valid"
        else [acquire, finish, acquire, result]
    )
    process = Process(frames)

    class Resources:
        acquired = 0
        finished = 0

        def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
            self.acquired += 1
            return identity

        def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
            assert ticket == identity
            self.finished += 1

    resources = Resources()
    proxy = ProviderProxy(cast(OwnedProcess, process))
    if mode == "valid":
        assert proxy.acquire(boundary, resources=resources).body == BODY
        assert not process.poisoned
    else:
        with pytest.raises(RuntimeError):
            proxy.acquire(boundary, resources=resources)
        assert process.poisoned
    assert resources.acquired == resources.finished == (0 if mode == "missing" else 1)
