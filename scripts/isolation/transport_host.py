"""Pure exact accounting for uniquely owned ephemeral bridge/veth artifacts."""

import ipaddress
import json
import re
from collections import Counter
from typing import Any


def link_local(mac: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        raise RuntimeError("Invalid owned MAC")
    octets = bytearray.fromhex(mac.replace(":", ""))
    if octets[0] & 1:
        raise RuntimeError("Multicast owned MAC")
    octets[0] ^= 2
    return str(
        ipaddress.IPv6Address(
            bytes.fromhex("fe80000000000000") + octets[:3] + b"\xff\xfe" + octets[3:]
        )
    )


def kernel_routes(name: str, address: str) -> list[dict[str, Any]]:
    common = {"dev": name, "protocol": "kernel", "flags": [], "pref": "medium"}
    return [
        {**common, "dst": "fe80::/64", "metric": 256},
        {**common, "dst": "fe80::", "metric": 0, "table": "local", "type": "anycast"},
        {**common, "dst": address, "metric": 0, "table": "local", "type": "local"},
        {
            **common,
            "dst": "ff00::/8",
            "metric": 256,
            "table": "local",
            "type": "multicast",
        },
    ]


def counted(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(json.dumps(row, sort_keys=True) for row in rows)


def validate_owned_host(
    baseline: dict[str, Any],
    current: dict[str, Any],
    links: list[dict[str, Any]],
    bridge: str,
    peers: dict[str, dict[str, int]],
    disabled: str,
) -> dict[str, str]:
    """Only validated owned rows are accounted separately; original baseline survives."""
    if disabled not in ("1", "1\n") or not re.fullmatch(r"em[0-9a-f]{10}", bridge):
        raise RuntimeError("Owned bridge IPv6 delivery not disabled")
    if current["rules"] != baseline["rules"]:
        raise RuntimeError("Host routing rules changed")
    before = baseline["addresses"]
    old_names = {row["ifname"] for row in before}
    if len(old_names) != len(before) or bridge in old_names:
        raise RuntimeError("Ambiguous original interfaces")
    preserved = [row for row in current["addresses"] if row["ifname"] in old_names]
    if preserved != before:
        raise RuntimeError("Preexisting host interfaces changed")
    added = [row for row in current["addresses"] if row["ifname"] not in old_names]
    masters = [row for row in added if row["ifname"] == bridge]
    if len(masters) != 1 or masters[0].get("addr_info") != []:
        raise RuntimeError("Owned bridge has host addresses or is ambiguous")
    detail = {row["ifname"]: row for row in links}
    if (
        len(detail) != len(links)
        or detail.get(bridge, {}).get("linkinfo", {}).get("info_kind") != "bridge"
    ):
        raise RuntimeError("Owned bridge link kind missing")
    slaves = [row for row in added if row["ifname"] != bridge]
    if len(slaves) != len(peers) or len(peers) not in (0, 3):
        raise RuntimeError("Owned endpoint count differs")
    if peers and set(peers) != {"gateway", "fixture-a", "fixture-b"}:
        raise RuntimeError("Unexpected owned endpoint roles")
    if any(
        set(peer) != {"host_ifindex", "guest_ifindex"}
        or type(peer["guest_ifindex"]) is not int
        or peer["guest_ifindex"] <= 0
        for peer in peers.values()
    ):
        raise RuntimeError("Invalid owned peer evidence")
    expected_indices = {peer["host_ifindex"] for peer in peers.values()}
    if len(expected_indices) != len(peers) or any(
        type(value) is not int or value <= 0 for value in expected_indices
    ):
        raise RuntimeError("Ambiguous owned peer indices")
    netns: set[int] = set()
    accounted: list[dict[str, Any]] = []
    targets: dict[str, str] = {}
    for row in slaves:
        name = row["ifname"]
        matches = [
            role for role, peer in peers.items() if peer["host_ifindex"] == row.get("ifindex")
        ]
        if len(matches) != 1:
            raise RuntimeError("Unrelated host interface")
        role = matches[0]
        peer = peers[role]
        ns = row.get("link_netnsid")
        if (
            not re.fullmatch(r"veth[0-9a-f]{7}", name)
            or row.get("master") != bridge
            or row.get("link_index") != peer["guest_ifindex"]
            or type(ns) is not int
            or ns < 0
            or ns in netns
            or detail.get(name, {}).get("linkinfo", {}).get("info_kind") != "veth"
            or detail.get(name, {}).get("linkinfo", {}).get("info_slave_kind") != "bridge"
            or detail.get(name, {}).get("ifindex") != row.get("ifindex")
            or detail.get(name, {}).get("master") != bridge
            or detail.get(name, {}).get("link_index") != peer["guest_ifindex"]
        ):
            raise RuntimeError("Owned veth membership/peer is ambiguous")
        netns.add(ns)
        address = link_local(row["address"])
        expected_address = {
            "family": "inet6",
            "local": address,
            "prefixlen": 64,
            "scope": "link",
            "valid_life_time": 4294967295,
            "preferred_life_time": 4294967295,
        }
        if row.get("addr_info") != [expected_address]:
            raise RuntimeError("Unexpected owned host address")
        accounted.extend(kernel_routes(name, address))
        targets[role] = address
    # Partition only after every owned endpoint has been validated. Original
    # route-list equality stays literal; only ephemeral owned rows may reorder.
    owned_names = {row["ifname"] for row in slaves}
    original_routes = [row for row in current["routes"] if row.get("dev") not in owned_names]
    owned_routes = [row for row in current["routes"] if row.get("dev") in owned_names]
    if original_routes != baseline["routes"] or counted(owned_routes) != counted(accounted):
        raise RuntimeError("Unexpected host route change")
    return targets
