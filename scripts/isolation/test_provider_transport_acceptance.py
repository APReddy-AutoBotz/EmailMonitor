"""Actual provider requests in a fresh instance of the unchanged owned topology.

Separate module lifetime preserves the existing per-guest command/output caps and
legacy held-response polling budget. No broader network or sandbox profile exists.
"""

import json
import time
from uuid import UUID

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.fetching.sciencedirect import (
    CredentialReference,
    ProviderBinding,
    ProviderBoundary,
    ProviderRequest,
)
from emailmonitor.sources.sciencedirect import SearchRequest
from test_transport_acceptance import configure, snapshot
from test_transport_acceptance import topology as topology
from transport_manifest import ENDPOINTS
from transport_provider import ProviderProxy
from transport_topology import Topology


def provider_boundary(*, article: bool = False) -> ProviderBoundary:
    request = ProviderRequest(
        article=XML_IDENTIFIER if article else None,
        search=None if article else SearchRequest(query='  "Synthetic" AND topic  ', show=10),
    )
    binding = ProviderBinding(
        organization=UUID(int=1),
        job=UUID(int=2),
        item=UUID(int=3),
        lease=UUID(int=4),
        generation=1,
        deletion_generation=1,
        policy_version=1,
        policy_revision=1,
        discovery_revision=1,
        request_fingerprint=request.fingerprint,
        credential=CredentialReference(organization=UUID(int=1), reference=UUID(int=5), revision=1),
        deadline=time.monotonic() + 20,
    )
    # Deliberately controlled comparison state, never a real-source policy grant.
    return ProviderBoundary(request, binding, lambda: binding)


@pytest.mark.parametrize("family", [4, 6])
def test_actual_provider_put_and_get_xml_to_isolated_parser(
    topology: Topology, family: int
) -> None:
    from emailmonitor.extraction.provider_xml import parse_response

    configure(topology)
    proxy = ProviderProxy(topology.processes["gateway"])
    boundary = provider_boundary()
    acquired = proxy.acquire(boundary, family=family)
    assert boundary.parse_search(acquired).reported_total == 0
    assert proxy.finished == [(200, "")]
    calls = snapshot(topology)["calls"]
    assert len(calls) == 1
    first = calls[0]
    assert first["method"] == "PUT" and first["path"] == "/content/search/sciencedirect"
    assert first["body"].encode("ascii") == boundary.request.plan().body
    assert json.loads(first["body"])["qs"] == '  "Synthetic" AND topic  '
    assert first["credential_valid"] and first["sni"] == "api.elsevier.com"
    assert first["headers"] == {
        "Host": "api.elsevier.com",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "X-ELS-APIKey": "[synthetic-redacted]",
        "Content-Type": "application/json",
        "Content-Length": str(len(first["body"].encode())),
    }
    boundary = provider_boundary(article=True)
    acquired = proxy.acquire(boundary, family=family)
    observed = parse_response(
        Settings(environment="test", fixture_mode=True),
        boundary,
        acquired,
        profile="article_retrieval_response",
    )
    assert len(observed.observation.authors) == 3 and len(observed.observation.candidates) == 2
    assert observed.acquisition is acquired
    second = snapshot(topology)["calls"][1]
    assert second["method"] == "GET" and second["body"] == ""
    assert second["credential_valid"] and second["headers"]["Accept"] == "text/xml"
    assert "Content-Type" not in second["headers"] and "Content-Length" not in second["headers"]
    assert proxy.peers == [
        [ENDPOINTS["fixture-a"][0 if family == 4 else 1], 443, "api.elsevier.com"]
    ]
    assert len(snapshot(topology)["queries"]) == 4
    print(
        json.dumps(
            {
                "provider_put_get_isolated_xml": True,
                "family": family,
                "observed_authors": 3,
                "observed_candidates": 2,
                "actual_selected_peers": proxy.peers,
            }
        ),
        flush=True,
    )


@pytest.mark.parametrize(
    "mode",
    [
        "provider_redirect",
        "provider_forbidden",
        "provider_throttle",
        "provider_html",
        "provider_duplicate",
        "provider_short",
        "provider_extra",
        "provider_large",
        "mixed",
        "private",
        "wrong_name",
    ],
)
def test_actual_provider_failure_never_retries_or_releases(topology: Topology, mode: str) -> None:
    configure(topology, mode)
    target = ProviderProxy(topology.processes["gateway"])
    with pytest.raises(FetchDenied):
        target.acquire(provider_boundary(article=True))
    calls = snapshot(topology)["calls"]
    assert len(calls) == (0 if mode in ("mixed", "private", "wrong_name") else 1)
    assert len(snapshot(topology)["queries"]) == 2
    assert len(target.finished) == 1
    if mode == "provider_throttle":
        assert target.finished == [(429, "3")]


def test_actual_provider_untrusted_ca_sends_no_credential(topology: Topology) -> None:
    configure(topology)
    target = ProviderProxy(topology.processes["gateway"])
    with pytest.raises(FetchDenied):
        target.acquire(provider_boundary(), ca="untrusted")
    assert snapshot(topology)["calls"] == []
    assert len(snapshot(topology)["queries"]) == 2
    assert target.finished == [(None, "")]


@pytest.mark.parametrize("field", ["deletion_generation", "lease", "policy_revision"])
def test_actual_provider_changed_binding_after_response_discards_bytes(
    topology: Topology, field: str
) -> None:
    configure(topology)
    initial = provider_boundary(article=True)
    current = [initial.binding]
    boundary = ProviderBoundary(initial.request, initial.binding, lambda: current[0])
    target = ProviderProxy(topology.processes["gateway"])

    def revoke() -> None:
        assert len(snapshot(topology)["calls"]) == 1
        current[0] = current[0].model_copy(update={field: UUID(int=99) if field == "lease" else 2})

    with pytest.raises(FetchDenied):
        target.acquire(boundary, after_finish=revoke)
    assert target.finished == [(200, "")]
    assert len(snapshot(topology)["calls"]) == 1 and len(snapshot(topology)["queries"]) == 2
    with pytest.raises(FetchDenied):
        target.acquire(boundary)
    assert len(snapshot(topology)["queries"]) == 2
