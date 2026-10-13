"""Pure host artifact and bounded denial contracts; no sockets or Docker."""

import copy
import errno
import socket
from typing import Any

import pytest
import transport_routes
from transport_host import kernel_routes, link_local, validate_owned_host

BRIDGE = "em0123456789"


def states() -> tuple[
    dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, dict[str, int]]
]:
    baseline: dict[str, Any] = {
        "addresses": [{"ifname": "eth0", "addr_info": []}],
        "routes": [],
        "rules": [],
    }
    current = copy.deepcopy(baseline)
    current["addresses"].append({"ifname": BRIDGE, "addr_info": []})
    links: list[dict[str, Any]] = [{"ifname": BRIDGE, "linkinfo": {"info_kind": "bridge"}}]
    peers = {}
    for number, role in enumerate(("gateway", "fixture-a", "fixture-b"), 1):
        name = f"veth{number:07x}"
        mac = f"02:00:00:00:00:{number:02x}"
        address = link_local(mac)
        peers[role] = {"host_ifindex": number + 10, "guest_ifindex": 2}
        current["addresses"].append(
            {
                "ifname": name,
                "ifindex": number + 10,
                "master": BRIDGE,
                "link_index": 2,
                "link_netnsid": number,
                "address": mac,
                "addr_info": [
                    {
                        "family": "inet6",
                        "local": address,
                        "prefixlen": 64,
                        "scope": "link",
                        "valid_life_time": 4294967295,
                        "preferred_life_time": 4294967295,
                    }
                ],
            }
        )
        links.append(
            {
                "ifname": name,
                "ifindex": number + 10,
                "master": BRIDGE,
                "link_index": 2,
                "linkinfo": {"info_kind": "veth", "info_slave_kind": "bridge"},
            }
        )
        current["routes"] += kernel_routes(name, address)
    return baseline, current, links, peers


def test_exact_owned_artifacts_preserve_original_baseline() -> None:
    before, current, links, peers = states()
    original = copy.deepcopy(before)
    assert set(validate_owned_host(before, current, links, BRIDGE, peers, "1\n")) == set(peers)
    assert before == original
    current["routes"].reverse()
    assert len(validate_owned_host(before, current, links, BRIDGE, peers, "1")) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "unrelated",
        "old",
        "master",
        "index",
        "peer",
        "namespace",
        "kind",
        "bridge-kind",
        "detail-master",
        "detail-index",
        "slave-kind",
        "bridge-address",
        "family",
        "extra-address",
        "global",
        "lifetime",
        "route",
        "route-field",
        "duplicate-route",
        "missing-route",
        "rules",
        "ambiguous-peer",
        "duplicate-interface",
        "disabled",
    ],
)
def test_unexpected_host_reachability_or_ambiguous_ownership_refuses(mutation: str) -> None:
    before, current, links, peers = states()
    row = current["addresses"][2]
    disabled = "1"
    if mutation == "unrelated":
        current["addresses"].append({"ifname": "alien", "addr_info": []})
    elif mutation == "old":
        current["addresses"][0]["addr_info"] = [{"local": "192.0.2.2"}]
    elif mutation == "master":
        row["master"] = "other"
    elif mutation == "index":
        row["ifindex"] = 999
    elif mutation == "peer":
        row["link_index"] = 3
    elif mutation == "namespace":
        current["addresses"][3]["link_netnsid"] = row["link_netnsid"]
    elif mutation == "kind":
        links[1]["linkinfo"]["info_kind"] = "tun"
    elif mutation == "detail-master":
        links[1]["master"] = "other"
    elif mutation == "detail-index":
        links[1]["ifindex"] = 999
    elif mutation == "slave-kind":
        links[1]["linkinfo"]["info_slave_kind"] = "other"
    elif mutation == "bridge-kind":
        links[0]["linkinfo"]["info_kind"] = "veth"
    elif mutation == "bridge-address":
        current["addresses"][1]["addr_info"] = [{"local": "::1"}]
    elif mutation == "family":
        row["addr_info"][0]["family"] = "inet"
    elif mutation == "extra-address":
        row["addr_info"].append({"local": "127.0.0.1"})
    elif mutation == "global":
        row["addr_info"][0]["local"] = "2001:db8::1"
    elif mutation == "lifetime":
        row["addr_info"][0]["valid_life_time"] = 1
    elif mutation == "route":
        current["routes"].append({"dst": "default", "gateway": "8.8.8.1"})
    elif mutation == "route-field":
        current["routes"][0]["gateway"] = "fe80::1"
    elif mutation == "duplicate-route":
        current["routes"].append(current["routes"][0])
    elif mutation == "missing-route":
        current["routes"].pop()
    elif mutation == "rules":
        current["rules"].append({"table": 100})
    elif mutation == "ambiguous-peer":
        peers["fixture-a"] = peers["gateway"]
    elif mutation == "duplicate-interface":
        current["addresses"].append(row)
    elif mutation == "disabled":
        disabled = "0"
    with pytest.raises(RuntimeError):
        validate_owned_host(before, current, links, BRIDGE, peers, disabled)


def test_before_start_accepts_only_addressless_owned_master() -> None:
    before, current, links, _ = states()
    current["addresses"] = current["addresses"][:2]
    current["routes"] = []
    assert validate_owned_host(before, current, links[:1], BRIDGE, {}, "1") == {}


@pytest.mark.parametrize("outcome", ["denied", "success", "refused", "unknown", "external-timeout"])
def test_fixed_escape_contract_requires_actual_denials(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    monkeypatch.setattr(transport_routes, "evidence", lambda role: {"host_ifindex": 11})
    monkeypatch.setattr(socket, "if_nametoindex", lambda name: 2)
    endpoints = []

    class FakeSocket:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def settimeout(self, seconds: float) -> None:
            assert seconds == 0.25

        def connect(self, endpoint: tuple[Any, ...]) -> None:
            endpoints.append(endpoint)
            if outcome == "success":
                return
            if outcome == "refused":
                raise OSError(errno.ECONNREFUSED, "refused")
            if outcome == "unknown":
                raise OSError(errno.EINVAL, "unknown")
            if endpoint[0] in ("192.0.2.1", "2001:db8::1") and outcome != "external-timeout":
                raise OSError(errno.ENETUNREACH, "no route")
            raise TimeoutError("bounded")

    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    if outcome == "denied":
        result = transport_routes.escape_evidence("gateway", "fe80::ff:fe00:1")
        assert len(result["denials"]) == 5 and endpoints[-1] == ("fe80::ff:fe00:1", 443, 0, 2)
    else:
        with pytest.raises(RuntimeError):
            transport_routes.escape_evidence("gateway", "fe80::ff:fe00:1")


def test_preexisting_route_order_remains_strict_while_owned_rows_may_reorder() -> None:
    before, current, links, peers = states()
    original_routes = [
        {"dst": "192.0.2.0/24", "dev": "eth0"},
        {"dst": "2001:db8::/64", "dev": "eth0"},
    ]
    before["routes"] = copy.deepcopy(original_routes)
    current["routes"] = original_routes + list(reversed(current["routes"]))
    assert len(validate_owned_host(before, current, links, BRIDGE, peers, "1")) == 3
    current["routes"][:2] = reversed(current["routes"][:2])
    with pytest.raises(RuntimeError, match="route change"):
        validate_owned_host(before, current, links, BRIDGE, peers, "1")


def tentative() -> tuple[
    dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, dict[str, int]]
]:
    before, current, links, peers = states()
    row = current["addresses"][2]
    row["addr_info"][0]["tentative"] = True
    current["routes"] = [
        r for r in current["routes"] if r["dev"] != row["ifname"] or r.get("type") == "multicast"
    ]
    return before, current, links, peers


def test_tentative_owned_state_is_pending_never_transport_ready() -> None:
    from transport_host import OwnedDadPending, observe_owned_host

    before, current, links, peers = tentative()
    with pytest.raises(OwnedDadPending):
        observe_owned_host(before, current, links, BRIDGE, peers, "1")
    with pytest.raises(RuntimeError, match="host address"):
        validate_owned_host(before, current, links, BRIDGE, peers, "1")


@pytest.mark.parametrize(
    "mutation",
    [
        "dadfailed",
        "extra_flag",
        "false",
        "integer",
        "wrong_address",
        "extra_family",
        "unrelated",
        "old",
        "rules",
        "extra_route",
        "duplicate_route",
        "settled_missing_route",
        "owner",
        "disabled",
        "old_route_order",
    ],
)
def test_pending_never_masks_unexpected_state(mutation: str) -> None:
    from transport_host import OwnedDadPending, observe_owned_host

    before, current, links, peers = tentative()
    row = current["addresses"][2]
    disabled = "1"
    if mutation == "dadfailed":
        row["addr_info"][0]["dadfailed"] = True
    elif mutation == "extra_flag":
        row["addr_info"][0]["deprecated"] = True
    elif mutation == "false":
        row["addr_info"][0]["tentative"] = False
    elif mutation == "integer":
        row["addr_info"][0]["tentative"] = 1
    elif mutation == "wrong_address":
        row["addr_info"][0]["local"] = "fe80::dead"
    elif mutation == "extra_family":
        row["addr_info"].append({"family": "inet", "local": "192.0.2.1"})
    elif mutation == "unrelated":
        current["addresses"].append({"ifname": "unrelated", "addr_info": []})
    elif mutation == "old":
        current["addresses"][0]["mtu"] = 1
    elif mutation == "rules":
        current["rules"].append({"priority": 100})
    elif mutation == "extra_route":
        current["routes"].append({"dev": row["ifname"], "dst": "::/0"})
    elif mutation == "duplicate_route":
        current["routes"].append(copy.deepcopy(current["routes"][0]))
    elif mutation == "settled_missing_route":
        current["routes"].pop()
    elif mutation == "owner":
        peers["fixture-b"]["host_ifindex"] = peers["fixture-a"]["host_ifindex"]
    elif mutation == "disabled":
        disabled = "0"
    else:
        before["routes"] = [
            {"dev": "eth0", "dst": "192.0.2.0/24"},
            {"dev": "eth0", "dst": "2001:db8::/64"},
        ]
        current["routes"] = list(reversed(before["routes"])) + current["routes"]
    with pytest.raises(RuntimeError) as error:
        observe_owned_host(before, current, links, BRIDGE, peers, disabled)
    assert not isinstance(error.value, OwnedDadPending)


@pytest.mark.parametrize("outcome", ["settled", "timeout", "unexpected", "late_success"])
def test_owned_dad_wait_is_bounded_and_retries_only_pending(outcome: str) -> None:
    from transport_host import OwnedDadPending, observe_owned_host, settle_owned_dad

    now = [0.0]
    calls = [0]

    def observe(deadline: float) -> None:
        assert deadline == 5
        calls[0] += 1
        if outcome == "unexpected":
            raise RuntimeError("unexpected")
        if outcome == "late_success":
            now[0] = 6
            return
        if outcome == "settled" and calls[0] == 2:
            before, current, links, peers = states()
            assert len(observe_owned_host(before, current, links, BRIDGE, peers, "1")) == 3
            return
        before, current, links, peers = tentative()
        with pytest.raises(OwnedDadPending):
            observe_owned_host(before, current, links, BRIDGE, peers, "1")
        raise OwnedDadPending("pending")

    def sleep(seconds: float) -> None:
        assert 0 < seconds <= 0.1
        now[0] += seconds

    if outcome == "settled":
        settle_owned_dad(observe, clock=lambda: now[0], sleep=sleep)
        assert calls[0] == 2
    else:
        with pytest.raises(RuntimeError):
            settle_owned_dad(observe, clock=lambda: now[0], sleep=sleep)
        if outcome in ("unexpected", "late_success"):
            assert calls[0] == 1
        else:
            assert now[0] == 5 and calls[0] <= 52


@pytest.mark.parametrize("now", [0.0, 4.9, 5.0, 6.0])
def test_readiness_subprocess_budget_is_shared_and_expires(now: float) -> None:
    from transport_host import remaining_read_budget

    if now < 5:
        assert remaining_read_budget(5, clock=lambda: now) == 5 - now
    else:
        with pytest.raises(RuntimeError, match="deadline"):
            remaining_read_budget(5, clock=lambda: now)


def test_baseline_reads_share_remaining_observation_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import transport_topology

    budgets = iter([5.0, 4.0, 3.0, 2.0, 1.0])
    seen: list[float] = []
    monkeypatch.setattr(transport_topology, "remaining_read_budget", lambda deadline: next(budgets))

    def read(*args: str, timeout: float) -> list[dict[str, Any]]:
        seen.append(timeout)
        return []

    monkeypatch.setattr(transport_topology, "ip", read)
    assert transport_topology.host_baseline(5) == {"addresses": [], "routes": [], "rules": []}
    assert seen == [5, 4, 3, 2, 1]


@pytest.mark.parametrize("invalid_container", [False, True])
def test_pending_host_state_still_checks_container_ownership(
    monkeypatch: pytest.MonkeyPatch, invalid_container: bool
) -> None:
    import json
    import subprocess
    from pathlib import Path

    import transport_topology
    from transport_host import OwnedDadPending

    topology = transport_topology.Topology.__new__(transport_topology.Topology)
    before, current, links, peers = tentative()
    topology.baseline = before
    topology.name = "owned-network"
    topology.bridge = BRIDGE
    topology.owner = "owner"
    topology.identifiers = {"gateway": "container"}
    topology.images = ["fixture", "gateway"]
    topology.image_provenance = {"gateway": {"image_id": "image"}}
    topology.peer_evidence = peers
    network = {"Id": "network"}
    container = {
        "Image": "image",
        "NetworkSettings": {
            "Networks": {
                "owned-network": {
                    "NetworkID": "network",
                    "EndpointID": "a" * 64,
                    "IPPrefixLen": 29,
                    "GlobalIPv6PrefixLen": 64,
                }
            }
        },
    }
    checked: list[str] = []

    def owner(kind: str, metadata: dict[str, Any], expected: str) -> None:
        checked.append(kind)
        if kind == "container" and invalid_container:
            raise RuntimeError("Unowned container")

    monkeypatch.setattr(transport_topology, "require_owner", owner)
    monkeypatch.setattr(transport_topology, "validate_network", lambda *args: None)
    monkeypatch.setattr(transport_topology, "validate_container", lambda *args: None)
    monkeypatch.setattr(transport_topology, "check_host_ipv6_forwarding", lambda: None)
    monkeypatch.setattr(transport_topology, "host_baseline", lambda: current)
    monkeypatch.setattr(
        transport_topology,
        "ip",
        lambda *args: links if args[0] == "-details" else [{"addr_info": []}],
    )
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: "1")
    monkeypatch.setattr(
        transport_topology,
        "docker",
        lambda *args: subprocess.CompletedProcess(
            args, 0, json.dumps([network if args[0] == "network" else container])
        ),
    )
    with pytest.raises(RuntimeError) as error:
        topology.inspect(allow_pending=True)
    assert checked == ["network", "container"]
    assert isinstance(error.value, OwnedDadPending) is (not invalid_container)
