"""Pure topology/route contracts; never execute Docker or network operations."""

import copy
import ipaddress
import socket
import struct
from typing import Any

import pytest
from emailmonitor.fetching.safety import public_addresses
from transport_manifest import ENDPOINTS, IPAM_GATEWAYS, V4_SUBNET, V6_SUBNET
from transport_routes import attributes, validate_routes
from transport_topology import overlaps, validate_container, validate_network


def network() -> dict[str, Any]:
    return {
        "Name": "owned",
        "Driver": "bridge",
        "Scope": "local",
        "Internal": True,
        "EnableIPv4": True,
        "EnableIPv6": True,
        "Ingress": False,
        "ConfigOnly": False,
        "IPAM": {
            "Driver": "default",
            "Options": None,
            "Config": [
                {"Subnet": V4_SUBNET, "Gateway": IPAM_GATEWAYS[0]},
                {"Subnet": V6_SUBNET, "Gateway": IPAM_GATEWAYS[1]},
            ],
        },
        "Options": {
            "com.docker.network.bridge.name": "owned0",
            "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
            "com.docker.network.bridge.gateway_mode_ipv6": "isolated",
            "com.docker.network.bridge.enable_ip_masquerade": "false",
        },
        "Containers": {"container": {}},
    }


def test_manifest_public_addresses_are_synthetic_only_and_disjoint() -> None:
    addresses = tuple(value for endpoint in ENDPOINTS.values() for value in endpoint)
    assert len(set(addresses)) == 6 and public_addresses(addresses) == frozenset(addresses)
    for endpoint in ENDPOINTS.values():
        assert ipaddress.ip_address(endpoint[0]) in ipaddress.ip_network(V4_SUBNET)
        assert ipaddress.ip_address(endpoint[1]) in ipaddress.ip_network(V6_SUBNET)
    assert not set(addresses) & set(IPAM_GATEWAYS)
    assert overlaps("8.8.8.0/24") and overlaps(ENDPOINTS["gateway"][0])
    assert overlaps(V6_SUBNET) and not overlaps("10.0.0.0/8")


def test_network_requires_exact_isolated_dual_stack_manifest() -> None:
    value = network()
    validate_network(value, "owned", "owned0", {"container"})
    reordered = copy.deepcopy(value)
    reordered["IPAM"]["Config"].reverse()
    reordered["IPAM"]["Config"][0]["IPRange"] = ""
    validate_network(reordered, "owned", "owned0", {"container"})
    for key, replacement in (
        ("Internal", False),
        ("EnableIPv6", False),
        ("Ingress", True),
        ("Containers", {"unexpected": {}}),
        ("Driver", "host"),
    ):
        modified = copy.deepcopy(value)
        modified[key] = replacement
        with pytest.raises(RuntimeError):
            validate_network(modified, "owned", "owned0", {"container"})
    for key in value["Options"]:
        modified = copy.deepcopy(value)
        modified["Options"][key] = "unsafe"
        with pytest.raises(RuntimeError):
            validate_network(modified, "owned", "owned0", {"container"})


def container() -> dict[str, Any]:
    host = {
        "NetworkMode": "owned",
        "Privileged": False,
        "CapAdd": None,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "ReadonlyRootfs": True,
        "Binds": None,
        "Devices": [],
        "DeviceRequests": None,
        "PortBindings": {},
        "ExtraHosts": None,
        "Links": None,
        "PidMode": "",
        "IpcMode": "private",
        "Sysctls": {},
        "Dns": ["127.0.0.1"],
        "DnsSearch": ["."],
        "Memory": 268435456,
        "MemorySwap": 268435456,
        "NanoCpus": 500000000,
        "PidsLimit": 64,
    }
    endpoint = {
        "IPAddress": ENDPOINTS["gateway"][0],
        "GlobalIPv6Address": ENDPOINTS["gateway"][1],
        "Gateway": "",
        "IPv6Gateway": "",
        "IPAMConfig": {
            "IPv4Address": ENDPOINTS["gateway"][0],
            "IPv6Address": ENDPOINTS["gateway"][1],
        },
    }
    return {
        "HostConfig": host,
        "Config": {"User": "65532:65532", "Env": ["EM_TRANSPORT_ROLE=gateway"]},
        "Mounts": [],
        "NetworkSettings": {"Networks": {"owned": endpoint}, "Ports": {}},
    }


def test_container_rejects_mounts_caps_dns_routes_and_external_attachment() -> None:
    value = container()
    validate_container(value, "owned", "gateway", True)
    validate_container(value, "owned", "gateway", False)
    nullable = copy.deepcopy(value)
    nullable["HostConfig"]["Sysctls"] = None
    validate_container(nullable, "owned", "gateway", True)
    for key, replacement in (
        ("Privileged", True),
        ("CapAdd", ["NET_ADMIN"]),
        ("Binds", ["/host:/guest"]),
        ("Dns", ["8.8.8.8"]),
        ("PortBindings", {"443/tcp": [{"HostPort": "443"}]}),
        ("Sysctls", {"unsafe": "1"}),
        ("PidMode", "host"),
        ("ReadonlyRootfs", False),
    ):
        modified = copy.deepcopy(value)
        modified["HostConfig"][key] = replacement
        with pytest.raises(RuntimeError):
            validate_container(modified, "owned", "gateway", True)
    for key in ("Gateway", "IPv6Gateway", "IPAddress"):
        modified = copy.deepcopy(value)
        modified["NetworkSettings"]["Networks"]["owned"][key] = "unexpected"
        with pytest.raises(RuntimeError):
            validate_container(modified, "owned", "gateway", True)


def rules() -> list[dict[str, int]]:
    return [
        {"family": family, "table": table, "priority": priority}
        for family, table, priority in (
            (socket.AF_INET, 255, 0),
            (socket.AF_INET, 254, 32766),
            (socket.AF_INET, 253, 32767),
            (socket.AF_INET6, 255, 0),
            (socket.AF_INET6, 254, 32766),
        )
    ]


def route(address: str = "8.8.8.0", prefix: int = 29) -> dict[str, Any]:
    return {
        "address": address,
        "prefix": prefix,
        "gateway": False,
        "multipath": False,
        "table": 254,
        "kind": 1,
        "interface": 2,
    }


def test_complete_routes_refuse_external_default_gateway_and_policy_selection() -> None:
    validate_routes(
        [route(), route("2001:4860:ffff:ee00::", 64), route("127.0.0.0", 8)], rules(), "gateway"
    )
    validate_routes([{**route("::", 0), "kind": 7}], rules(), "gateway")
    for candidate in (
        route("0.0.0.0", 0),
        route("::", 0),
        route("10.0.0.0", 8),
        route("8.8.0.0", 16),
        {**route(), "gateway": True},
        {**route(), "multipath": True},
        {**route(), "table": 123},
    ):
        with pytest.raises(RuntimeError):
            validate_routes([candidate], rules(), "gateway")
    for modified in (
        rules()[:-1],
        rules() + [rules()[0]],
        rules() + [{"family": socket.AF_INET, "table": 123, "priority": 1}],
    ):
        with pytest.raises(RuntimeError):
            validate_routes([route()], modified, "gateway")


def test_netlink_attributes_are_bounded_and_unambiguous() -> None:
    assert attributes(struct.pack("HHI", 8, 4, 2)) == {4: struct.pack("I", 2)}
    for raw in (
        b"x",
        struct.pack("HH", 3, 1),
        struct.pack("HH", 8, 1),
        struct.pack("HHI", 8, 4, 2) * 2,
    ):
        with pytest.raises(RuntimeError):
            attributes(raw)
