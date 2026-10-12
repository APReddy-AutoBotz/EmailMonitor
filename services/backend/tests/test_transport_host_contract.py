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
