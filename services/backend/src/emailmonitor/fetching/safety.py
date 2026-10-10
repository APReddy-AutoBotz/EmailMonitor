"""Validation primitives only. They do not implement OS or socket egress enforcement."""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class FetchDenied(Exception):
    """Safe reason only: never include a raw URL, token, credentials or source body."""


class IsolationUnavailable(FetchDenied):
    pass


@dataclass(frozen=True)
class SafeURL:
    normalized: str
    host: str
    path: str


def classify_url(value: str, allowed_hosts: frozenset[str]) -> SafeURL:
    if not value or len(value) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise FetchDenied("url_shape_denied")
    if "\\" in value:
        raise FetchDenied("url_shape_denied")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if parts.scheme != "https" or not host or parts.username is not None:
            raise FetchDenied("url_origin_denied")
        if (
            parts.port not in (None, 443)
            or parts.fragment
            or parts.query
            or "?" in value
            or "#" in value
        ):
            raise FetchDenied("url_scope_denied")
        # This offline slice supports exact ASCII registered fixture hosts only.
        # Unicode/IDNA source onboarding requires an explicitly reviewed manifest.
        if not host.isascii() or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise FetchDenied("host_denied")
        if (
            host.endswith(".")
            or any(
                not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                for label in host.split(".")
            )
            or len(host) > 253
        ):
            raise FetchDenied("host_denied")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise FetchDenied("literal_address_denied")
        if host not in allowed_hosts:
            raise FetchDenied("host_denied")
        path = parts.path or "/"
        if "%" in path or any(segment in (".", "..") for segment in path.split("/")):
            raise FetchDenied("path_denied")
        return SafeURL(urlunsplit(("https", host, path, "", "")), host, path)
    except ValueError:
        raise FetchDenied("url_shape_denied") from None


def public_addresses(records: tuple[str, ...]) -> frozenset[str]:
    if not records or len(records) > 32:
        raise FetchDenied("dns_records_denied")
    result: set[str] = set()
    for record in records:
        try:
            address = ipaddress.ip_address(record)
        except ValueError:
            raise FetchDenied("dns_address_denied") from None
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise FetchDenied("dns_address_denied")
        if isinstance(address, ipaddress.IPv6Address) and (
            address.ipv4_mapped is not None
            or address.scope_id is not None
            or address.sixtofour is not None
            or address.teredo is not None
        ):
            raise FetchDenied("dns_address_denied")
        result.add(str(address))
    return frozenset(result)


@dataclass(frozen=True)
class ConnectionPlan:
    """Tested pinning contract, NOT a verified socket connector or egress firewall."""

    hostname: str
    addresses: frozenset[str]
    port: int = 443

    @classmethod
    def from_records(cls, url: SafeURL, records: tuple[str, ...]) -> "ConnectionPlan":
        return cls(url.host, public_addresses(records))

    def validate_peer(self, peer: str, certificate_verified: bool) -> None:
        if public_addresses((peer,)) - self.addresses or not certificate_verified:
            raise FetchDenied("connection_peer_denied")
