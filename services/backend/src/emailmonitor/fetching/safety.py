"""Validation primitives only. They do not implement OS or socket egress enforcement."""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EUROPE_PMC_SEARCH_HOST = "www.ebi.ac.uk"
EUROPE_PMC_SEARCH_PATH = "/europepmc/webservices/rest/search"
_EUROPE_PMC_SEARCH_KEYS = ("query", "format", "resultType", "pageSize", "cursorMark")


def europe_pmc_search_query(query: str) -> bool:
    """Exact grammar of the typed Europe PMC search planner (OA-027).

    Parameter names, order and fixed values are closed; ``pageSize`` is 1-100; the
    cursor is the provider's opaque token alphabet; and the string must be the
    canonical encoding of its own parse, so no alternate spelling passes.
    """
    if not query or len(query) > 1900:
        return False
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
    except ValueError:
        return False
    if tuple(key for key, _ in pairs) != _EUROPE_PMC_SEARCH_KEYS:
        return False
    values = dict(pairs)
    text = values["query"]
    return (
        values["format"] == "json"
        and values["resultType"] == "lite"
        and re.fullmatch(r"[1-9][0-9]?|100", values["pageSize"]) is not None
        and re.fullmatch(r"[A-Za-z0-9*+/=_-]{1,512}", values["cursorMark"]) is not None
        and 1 <= len(text) <= 1100
        and text == text.strip()
        and not any(ord(c) < 32 or ord(c) == 127 for c in text)
        and urlencode(pairs) == query
    )


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
        # Only the typed Article Retrieval FULL selector is supported. This is
        # request syntax, never source permission; every other query stays denied.
        full_view = (
            host == "api.elsevier.com"
            and parts.query == "view=FULL"
            and value.count("?") == 1
            and re.fullmatch(
                r"/content/article/(?:doi/10\.[0-9]{4,9}/[A-Za-z0-9._;()/:-]+|pii/(?:S[A-Z0-9]{16}|B[A-Z0-9]{19}))",
                parts.path,
            )
            is not None
        )
        # Europe PMC search: the typed planner's exact grammar only (OA-027).
        epmc_search = (
            host == EUROPE_PMC_SEARCH_HOST
            and parts.path == EUROPE_PMC_SEARCH_PATH
            and value.count("?") == 1
            and europe_pmc_search_query(parts.query)
        )
        typed_query = full_view or epmc_search
        if (
            parts.port not in (None, 443)
            or parts.fragment
            or (bool(parts.query) and not typed_query)
            or ("?" in value and not typed_query)
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
        query = parts.query if typed_query else ""
        return SafeURL(
            urlunsplit(("https", host, path, query, "")),
            host,
            path + (f"?{query}" if query else ""),
        )
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
