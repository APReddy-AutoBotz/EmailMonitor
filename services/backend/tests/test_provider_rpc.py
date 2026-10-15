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
