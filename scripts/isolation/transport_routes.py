"""Read-only complete Linux route/rule netlink dumps; no configuration commands."""

import errno
import ipaddress
import json
import os
import secrets
import socket
import struct
from pathlib import Path
from typing import Any

from transport_manifest import ENDPOINTS, IPAM_GATEWAYS, V4_SUBNET, V6_SUBNET


def attributes(payload: bytes) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 4:
            raise RuntimeError("Incomplete route attribute")
        length, kind = struct.unpack_from("HH", payload, offset)
        if length < 4 or length > len(payload) - offset or kind in result:
            raise RuntimeError("Invalid route attribute")
        result[kind] = payload[offset + 4 : offset + length]
        offset += (length + 3) & ~3
    if offset != len(payload):
        raise RuntimeError("Incomplete route attribute padding")
    return result


def dump(request: int, response: int, family: int) -> list[bytes]:
    sequence = secrets.randbits(31)
    body = bytes([family]) + b"\0" * 11
    query = struct.pack("IHHII", 16 + len(body), request, 0x301, sequence, 0) + body
    records: list[bytes] = []
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, socket.NETLINK_ROUTE) as stream:
        stream.bind((0, 0))
        stream.settimeout(2)
        stream.sendto(query, (0, 0))
        total = 0
        while True:
            raw, ancillary, received_flags, peer = stream.recvmsg(65536)
            if ancillary or received_flags or peer != (0, 0):
                raise RuntimeError("Nonkernel netlink reply")
            total += len(raw)
            if total > 262144:
                raise RuntimeError("Route dump limit exceeded")
            offset = 0
            while offset < len(raw):
                if len(raw) - offset < 16:
                    raise RuntimeError("Incomplete netlink header")
                length, kind, flags, seq, _pid = struct.unpack_from("IHHII", raw, offset)
                if length < 16 or length > len(raw) - offset or seq != sequence or flags & 0x10:
                    raise RuntimeError("Interrupted or malformed route dump")
                payload = raw[offset + 16 : offset + length]
                offset += (length + 3) & ~3
                if kind == 3:
                    if offset != len(raw):
                        raise RuntimeError("Unexpected messages after dump completion")
                    if payload and (len(payload) != 4 or struct.unpack("i", payload)[0] != 0):
                        raise RuntimeError("Route dump completion error")
                    return records
                if kind != response:
                    raise RuntimeError("Unexpected route dump reply")
                records.append(payload)
                if len(records) > 256:
                    raise RuntimeError("Route count limit exceeded")


def route_records() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for family in (socket.AF_INET, socket.AF_INET6):
        for raw in dump(26, 24, family):
            if len(raw) < 12:
                raise RuntimeError("Incomplete route record")
            af, prefix, source_prefix, tos, table, _protocol, _scope, kind, flags = struct.unpack(
                "BBBBBBBBI", raw[:12]
            )
            attr = attributes(raw[12:])
            if af != family or source_prefix or tos or flags:
                raise RuntimeError("Unsupported route selection")
            destination = attr.get(1, b"\0" * (4 if family == socket.AF_INET else 16))
            address = str(ipaddress.ip_address(destination))
            table = struct.unpack("I", attr[15])[0] if 15 in attr else table
            result.append(
                {
                    "family": af,
                    "prefix": prefix,
                    "address": address,
                    "table": table,
                    "kind": kind,
                    "gateway": 5 in attr,
                    "multipath": bool(set(attr) & {9, 18, 19, 30}),
                    "interface": struct.unpack("I", attr[4])[0] if 4 in attr else 0,
                }
            )
    return result


def rule_records() -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for family in (socket.AF_INET, socket.AF_INET6):
        for raw in dump(34, 32, family):
            if len(raw) < 12:
                raise RuntimeError("Incomplete rule record")
            af, dst, src, tos, table, reserved, reserved2, action, flags = struct.unpack(
                "BBBBBBBBI", raw[:12]
            )
            attr = attributes(raw[12:])
            if (
                af != family
                or any((dst, src, tos, reserved, reserved2, flags))
                or action != 1
                or set(attr) - {6, 14, 15, 21}
            ):
                raise RuntimeError("Unexpected policy routing rule")
            if (14 in attr and attr[14] != struct.pack("I", 0xFFFFFFFF)) or (
                21 in attr and attr[21] != b"\x02"
            ):
                raise RuntimeError("Unexpected rule suppression or protocol")
            result.append(
                {
                    "family": af,
                    "table": struct.unpack("I", attr[15])[0] if 15 in attr else table,
                    "priority": struct.unpack("I", attr[6])[0] if 6 in attr else 0,
                }
            )
    return result


def validate_routes(routes: list[dict[str, Any]], rules: list[dict[str, int]], role: str) -> None:
    if role not in ENDPOINTS or not routes:
        raise RuntimeError("Missing route evidence")
    allowed = [
        ipaddress.ip_network(value)
        for value in (
            V4_SUBNET,
            V6_SUBNET,
            "127.0.0.0/8",
            "::1/128",
            "fe80::/64",
            "ff00::/8",
        )
    ]
    for route in routes:
        prefix = ipaddress.ip_network(f"{route['address']}/{route['prefix']}", strict=False)
        unreachable_default = (
            route["kind"] == 7 and route["prefix"] == 0 and route["address"] in ("0.0.0.0", "::")
        )
        if (
            route["gateway"]
            or route["multipath"]
            or route["table"] not in (254, 255)
            or (route["kind"] not in (1, 2, 3, 5) and not unreachable_default)
            or (
                not unreachable_default
                and not any(
                    type(prefix) is type(network)
                    and prefix.network_address in network
                    and prefix.prefixlen >= network.prefixlen
                    for network in allowed
                )
            )
        ):
            raise RuntimeError("External or unsupported guest route")
    expected = {
        (socket.AF_INET, 255, 0),
        (socket.AF_INET, 254, 32766),
        (socket.AF_INET, 253, 32767),
        (socket.AF_INET6, 255, 0),
        (socket.AF_INET6, 254, 32766),
    }
    actual = {(rule["family"], rule["table"], rule["priority"]) for rule in rules}
    if actual != expected or len(actual) != len(rules):
        raise RuntimeError("Unexpected routing policy")


def evidence(role: str) -> dict[str, Any]:
    if os.getuid() != 65532:
        raise RuntimeError("Nonroot diagnostic user required")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        any(
            int(status[name].strip(), 16)
            for name in ("CapEff", "CapPrm", "CapBnd", "CapInh", "CapAmb")
        )
        or status["NoNewPrivs"].strip() != "1"
        or status["Seccomp"].strip() != "2"
    ):
        raise RuntimeError("Missing process restrictions")
    required_cgroup = {
        "memory.max": "268435456",
        "memory.swap.max": "0",
        "pids.max": "64",
        "cpu.max": "50000 100000",
    }
    for filename, expected in required_cgroup.items():
        if (Path("/sys/fs/cgroup") / filename).read_text().strip() != expected:
            raise RuntimeError("Actual cgroup resource limit mismatch")
    import resource

    if resource.getrlimit(resource.RLIMIT_NOFILE) != (128, 128) or resource.getrlimit(
        resource.RLIMIT_CORE
    ) != (0, 0):
        raise RuntimeError("Actual process resource limits mismatch")
    interfaces = sorted(os.listdir("/sys/class/net"))
    if interfaces != ["eth0", "lo"]:
        raise RuntimeError("Unexpected network attachment")
    resolv = Path("/etc/resolv.conf").read_text()
    if len(resolv) > 4096:
        raise RuntimeError("Resolver configuration cap exceeded")
    nameservers: list[str] = []
    for line in resolv.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if fields[0] == "nameserver":
            if len(fields) != 2 or fields[1] not in ("127.0.0.1", "127.0.0.11"):
                raise RuntimeError("External resolver configuration")
            nameservers.append(fields[1])
        elif fields[0] == "search":
            if fields != ["search", "."]:
                raise RuntimeError("Unexpected search domain")
        elif fields[0] != "options":
            raise RuntimeError("Unexpected resolver directive")
    if len(nameservers) != 1:
        raise RuntimeError("Missing closed resolver")
    for filename in ("/proc/net/udp", "/proc/net/udp6"):
        for line in Path(filename).read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) < 2 or (
                fields[1].split(":")[-1] == "0035" and fields[1].split(":")[0] != "0B00007F"
            ):
                raise RuntimeError("Unexpected local DNS upstream listener")
    if (
        role.startswith("fixture-")
        and Path("/proc/sys/net/ipv4/ip_unprivileged_port_start").read_text().strip() != "443"
    ):
        raise RuntimeError("Fixture-only minimum port mismatch")
    routes, rules = route_records(), rule_records()
    validate_routes(routes, rules, role)
    if any(
        route["interface"] not in {socket.if_nametoindex("lo"), socket.if_nametoindex("eth0")}
        and not (route["kind"] == 7 and route["interface"] == 0)
        for route in routes
    ):
        raise RuntimeError("Unexpected route output interface")
    return {
        "role": role,
        "host_ifindex": int(Path("/sys/class/net/eth0/iflink").read_text()),
        "guest_ifindex": socket.if_nametoindex("eth0"),
        "interfaces": interfaces,
        "routes": routes,
        "rules": rules,
        "capabilities": 0,
        "cgroup_limits": required_cgroup,
        "seccomp": 2,
        "no_new_privileges": True,
        "resolv_conf": resolv,
    }


if __name__ == "__main__":
    print(json.dumps(evidence(os.environ["EM_TRANSPORT_ROLE"])))


def escape_evidence(role: str, peer: object) -> dict[str, Any]:
    """Fixed synthetic negative connects after fresh complete route validation."""
    current = evidence(role)
    if (
        type(peer) is not str
        or str(ipaddress.IPv6Address(peer)) != peer
        or not ipaddress.IPv6Address(peer).is_link_local
    ):
        raise RuntimeError("Invalid owned host-peer target")
    results: list[dict[str, Any]] = []
    targets = [
        (IPAM_GATEWAYS[0], False),
        (IPAM_GATEWAYS[1], False),
        ("192.0.2.1", True),
        ("2001:db8::1", True),
        (peer, False),
    ]
    for target, external in targets:
        family = socket.AF_INET6 if ":" in target else socket.AF_INET
        endpoint = (
            (target, 443, 0, socket.if_nametoindex("eth0"))
            if target == peer
            else ((target, 443, 0, 0) if family == socket.AF_INET6 else (target, 443))
        )
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(0.25)
            try:
                stream.connect(endpoint)
            except OSError as error:
                if external and error.errno != errno.ENETUNREACH:
                    raise RuntimeError("External no-route denial not established") from error
                if not external and not (
                    isinstance(error, TimeoutError)
                    or error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH)
                ):
                    raise RuntimeError("Host/gateway isolation denial not established") from error
                results.append(
                    {
                        "target": target,
                        "port": 443,
                        "errno": error.errno,
                        "timeout": isinstance(error, TimeoutError),
                    }
                )
            else:
                raise RuntimeError("Unexpected host/gateway/external connection")
    return {"role": role, "denials": results, "host_ifindex": current["host_ifindex"]}
