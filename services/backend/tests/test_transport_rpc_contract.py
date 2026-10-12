"""Owned-channel policy regressions without Docker or socket execution."""

import base64
import time
from typing import Any, cast
from uuid import UUID

import pytest
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.sources.policy import Operation
from transport_rpc import BrowserProxyMediator, GatewayProxy, OwnedProcess

HOST = "synthetic.publisher.example"
URL = f"https://{HOST}/tooltip.html"


class Stub:
    def __init__(self, changes: dict[str, object] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.poisoned = False
        self.step = 0
        self.changes = changes or {}

    def send(self, value: dict[str, object], deadline: float) -> None:
        self.sent.append(value)

    def receive(self, deadline: float) -> dict[str, Any]:
        self.step += 1
        if self.step == 1:
            fields = dict(self.sent[0]["scope"])
            fields.update(self.changes)
            return {"kind": "authorize", "scope": fields, "url": URL}
        return {
            "kind": "result",
            "status": "ok",
            "body": base64.b64encode(b"synthetic").decode(),
            "peers": [["8.8.8.3", 443, HOST]],
        }


def scope(operation: Operation) -> PlanScope:
    return PlanScope(
        UUID("11111111-1111-4111-8111-111111111111"),
        "synthetic-publisher",
        1,
        operation,
        frozenset({HOST}),
        time.monotonic() + 4,
        2,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"organization": "22222222-2222-4222-8222-222222222222"},
        {"source": "other"},
        {"policy_version": 2},
        {"operation": "export_contacts"},
        {"allowed_hosts": ["denied.fixture.example"]},
        {"deadline": 1},
        {"max_redirects": 5},
    ],
)
def test_gateway_callback_cannot_change_host_authorized_scope(changes: dict[str, object]) -> None:
    channel = Stub(changes)
    calls: list[str] = []
    target = GatewayProxy(
        cast(OwnedProcess, channel), scope, lambda bound, url: calls.append(url.path)
    )
    with pytest.raises(RuntimeError, match="scope mismatch"):
        target.fetch(URL)
    assert channel.poisoned and len(calls) == 1 and len(channel.sent) == 1


def test_host_current_policy_checked_before_each_reply_and_byte_release() -> None:
    channel = Stub()
    calls: list[str] = []

    def authorize(bound: PlanScope, url: SafeURL) -> None:
        calls.append(url.path)
        if len(calls) == 3:
            raise FetchDenied("source_policy_denied")

    target = GatewayProxy(cast(OwnedProcess, channel), scope, authorize)
    with pytest.raises(FetchDenied):
        target.fetch(URL)
    assert calls == ["/tooltip.html"] * 3
    assert channel.sent[1] == {"authorized": True}
    assert channel.sent[0]["ca"] == "fixture"


def test_browser_has_no_scope_family_credentials_or_arbitrary_method_controls() -> None:
    channel = Stub()
    target = GatewayProxy(cast(OwnedProcess, channel), scope, lambda bound, url: None)
    mediator = BrowserProxyMediator(target)
    valid = b'{"kind":"request","identifier":1,"url":"https://synthetic.publisher.example/tooltip.html","method":"GET","resource":"document"}'
    assert b'"status":"ok"' in mediator.reply(valid)
    for extra in (
        b',"scope":{}',
        b',"headers":{"Authorization":"synthetic"}',
        b',"family":6',
        b',"ca":"untrusted"',
    ):
        assert mediator.reply(valid[:-1] + extra + b"}") == b'{"status":"denied"}\n'
    assert mediator.reply(valid.replace(b'"GET"', b'"POST"')) == b'{"status":"denied"}\n'
    assert len(channel.sent) == 2


def test_off_domain_browser_frame_never_reaches_the_gateway() -> None:
    channel = Stub()
    target = GatewayProxy(cast(OwnedProcess, channel), scope, lambda bound, url: None)
    mediator = BrowserProxyMediator(target)
    assert (
        mediator.reply(
            b'{"kind":"request","identifier":1,"url":"https://denied.fixture.example/","method":"GET","resource":"fetch"}'
        )
        == b'{"status":"denied"}\n'
    )
    assert channel.sent == []


def test_successful_browser_peer_receipts_survive_later_denial_and_mutation() -> None:
    channel = Stub()
    target = GatewayProxy(cast(OwnedProcess, channel), scope, lambda bound, url: None)
    mediator = BrowserProxyMediator(target)
    frame = b'{"kind":"request","identifier":1,"url":"https://synthetic.publisher.example/tooltip.html","method":"GET","resource":"document"}'
    assert b'"status":"ok"' in mediator.reply(frame)
    original = target.peers
    original[0][0] = "mutated"
    assert mediator.selected_peers == (("8.8.8.3", 443, HOST),)
    assert (
        mediator.reply(frame.replace(HOST.encode(), b"denied.fixture.example"))
        == b'{"status":"denied"}\n'
    )
    assert target.peers == []
    assert mediator.selected_peers == (("8.8.8.3", 443, HOST),)
    assert (mediator.accepted, mediator.denied) == (1, 1)


def test_denied_release_never_fabricates_successful_browser_peer_receipt() -> None:
    channel = Stub()
    calls = 0

    def authorize(bound: PlanScope, url: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise FetchDenied("revoked_before_release")

    target = GatewayProxy(cast(OwnedProcess, channel), scope, authorize)
    mediator = BrowserProxyMediator(target)
    frame = b'{"kind":"request","identifier":1,"url":"https://synthetic.publisher.example/tooltip.html","method":"GET","resource":"document"}'
    assert mediator.reply(frame) == b'{"status":"denied"}\n'
    assert target.peers == [["8.8.8.3", 443, HOST]]
    assert mediator.selected_peers == ()
    assert (mediator.accepted, mediator.denied) == (0, 1)
