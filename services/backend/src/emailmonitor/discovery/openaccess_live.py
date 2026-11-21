"""Composition of the live Open Access path (OA-027). Disabled unless explicitly built.

Only owner-approved sources are enabled. Today that is Europe PMC (owner decision
2026-11-19, document 19); every other source is refused with ``source_not_enabled``
rather than silently answered from offline fixtures. Building this requires an
approval record and a protected transport; there is no production transport in
this repository yet, so callers receive ``live_transport_unavailable``.
"""

from __future__ import annotations

from emailmonitor.discovery.openaccess_orchestrator import OpenAccessOrchestrator
from emailmonitor.sources.europepmc_live import (
    EuropePmcLiveGateway,
    LiveSourceApproval,
    ProtectedTransport,
    SourceThrottle,
)


def live_europe_pmc_orchestrator(
    approval: LiveSourceApproval,
    transport: ProtectedTransport | None,
    *,
    reference_year: int | None = None,
    throttle: SourceThrottle | None = None,
) -> tuple[OpenAccessOrchestrator, EuropePmcLiveGateway]:
    """One gateway instance serves search and full text, so they share one throttle,
    one back-off state and one stop switch."""
    gateway = EuropePmcLiveGateway(approval, transport, throttle=throttle)
    orchestrator = OpenAccessOrchestrator(
        europe_pmc_gateway=gateway,
        europe_pmc_search_gateway=gateway,
        reference_year=reference_year,
        enabled_sources=frozenset({"europe-pmc"}),
    )
    return orchestrator, gateway
