"""Durable controlled-provider journey using the existing authority and result services.

There is deliberately no live composition or API-supplied transport. The injected
protected dispatch must be the reviewed controlled topology; SQL synthetic policy
only authorizes the durable fixture route, not the provider's real network origin.
"""

import time
from collections.abc import Callable
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from emailmonitor.administration.source import SourceAdmission, SourceLease
from emailmonitor.extraction.provider_xml import parse_response
from emailmonitor.extraction.xml_retained import retain_xml
from emailmonitor.extraction.xml_service import XmlExtraction
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url
from emailmonitor.fetching.sciencedirect import (
    AcquiredResponse,
    CredentialReference,
    ProviderBinding,
    ProviderBoundary,
    ProviderRequest,
)
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress, Work
from emailmonitor.sources import provider_documents as catalog
from emailmonitor.sources.access import current_policy
from emailmonitor.sources.policy import Operation
from emailmonitor.sources.sciencedirect import DiscoveryState, SearchRequest, advance


class ProviderDispatch(Protocol):
    def acquire(
        self, boundary: ProviderBoundary, *, resources: HopResources
    ) -> AcquiredResponse: ...


class BoundResources:
    """SQL resource ownership for one exact controlled mapping, never live admission."""

    def __init__(self, progress: Progress, work: Work, boundary: ProviderBoundary) -> None:
        self.admission = SourceAdmission(progress.database, progress.token, progress.settings)
        self.work, self.boundary = work, boundary

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        self.boundary.check_current()
        if (
            url.normalized != self.boundary.request.url
            or operation != self.boundary.request.operation
            or deadline != self.boundary.binding.deadline
        ):
            raise FetchDenied("controlled_provider_resource_denied")
        return self.admission.acquire(
            self.work.lease.organization,
            self.boundary.binding.policy_version,
            operation,
            classify_url(self.work.url, frozenset({"synthetic.publisher.example"})),
            deadline,
            self.work.lease.job,
        )

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        if type(ticket) is not SourceLease or ticket.organization != self.work.lease.organization:
            raise FetchDenied("controlled_provider_resource_denied")
        self.admission.finish(ticket, status, retry_after)


class ProviderJourney:
    def __init__(self, progress: Progress, dispatch: ProviderDispatch) -> None:
        # Progress already enforces the production/fixture configuration boundary.
        self.progress, self.dispatch = progress, dispatch
        self.xml = XmlExtraction(progress.database, progress.token, progress.settings)

    def _request(
        self, work: Work
    ) -> tuple[ProviderRequest, dict[str, object], tuple[catalog.ProviderDocument, ...]]:
        lease = work.lease
        if work.url not in catalog.URLS:
            raise FetchDenied("controlled_provider_route_denied")
        if work.kind == "discover":
            row = self.progress.discovery.prepare(lease.organization, lease.job)
            plan = row["plan"]
            if not isinstance(plan, dict) or plan.get("effective_query") not in (
                None,
                catalog.QUERY,
            ):
                raise FetchDenied("controlled_provider_query_denied")
            request = ProviderRequest(search=SearchRequest(query=catalog.QUERY, show=10))
            if work.url != catalog.SEARCH_URL:
                raise FetchDenied("controlled_provider_route_denied")
        else:
            row = self.xml.prepare(lease.organization, lease.job, work.url)
            request = None
        if row["source_id"] != catalog.SOURCE:
            raise FetchDenied("controlled_provider_source_denied")
        with self.progress.discovery._tenant(lease.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            _,
        ):
            # Fresh policy read after the lease/scope fence, never caller-owned policy.
            self.progress.discovery._authorize(
                c,
                lease.organization,
                lease.job,
                int(str(row["policy_version"])),
                work.url,
                work.kind == "discover",
            )
            policy = current_policy(c, lease.organization, str(row["source_id"]))
        registry = catalog.documents(policy["support"], str(row["source_id"]))
        if request is None:
            registered = next((d for d in registry if d.source_url == work.url), None)
            if registered is None:
                raise FetchDenied("provider_document_registry_denied")
            request = registered.request
        return request, {**row, "policy_revision": policy["row_version"]}, registry

    def boundary(self, work: Work) -> tuple[ProviderBoundary, tuple[catalog.ProviderDocument, ...]]:
        deadline = time.monotonic() + 20
        initial, _, registry = self._request(work)

        def current() -> ProviderBinding:
            try:
                request, row, fresh = self._request(work)
                if request != initial or fresh != registry:
                    raise FetchDenied("provider_document_registry_changed")
                lease = work.lease
                return ProviderBinding(
                    organization=lease.organization,
                    job=lease.job,
                    item=lease.item,
                    lease=lease.token,
                    generation=lease.generation,
                    deletion_generation=lease.deletion_generation,
                    policy_version=int(str(row["policy_version"])),
                    policy_revision=int(str(row["policy_revision"])),
                    discovery_revision=int(str(row["revision"])),
                    request_fingerprint=request.fingerprint,
                    # Opaque fixture reference; it cannot resolve a real credential.
                    credential=CredentialReference(
                        organization=lease.organization,
                        reference=uuid5(
                            NAMESPACE_URL, str(lease.organization) + ":controlled-provider"
                        ),
                        revision=1,
                    ),
                    deadline=deadline,
                )
            except (AuthorizationDenied, HTTPException, ValueError):
                raise FetchDenied("controlled_provider_authority_denied") from None

        initial_binding = current()
        return ProviderBoundary(initial, initial_binding, current), registry

    def process(self, work: Work, *, after_observation: Callable[[], None] | None = None) -> str:
        # Durable duplicate/recovery uses committed observations before any I/O.
        if after_observation is not None and not callable(after_observation):
            raise TypeError("Trusted completion callback required")
        lease = work.lease
        with bound(lease):
            existing = None
            if work.kind == "discover":
                from emailmonitor.discovery.state import DiscoveryState as DurableState

                row = self.progress.discovery.read(lease.organization, lease.job)
                if work.url in DurableState.model_validate(row["checkpoint"]).pages:
                    return self.progress.finish(work)
            if work.kind == "article":
                self.xml.prepare(lease.organization, lease.job, work.url)
                existing = next(
                    (
                        r
                        for r in self.progress.extraction.read(lease.organization, lease.job)
                        if r["article_url"] == work.url
                    ),
                    None,
                )
            if existing is None:
                boundary, registry = self.boundary(work)
                acquired = self.dispatch.acquire(
                    boundary, resources=BoundResources(self.progress, work, boundary)
                )
                boundary.require_response(acquired)
                if work.kind == "discover":
                    from emailmonitor.discovery.search import SearchPage

                    parsed = boundary.parse_search(acquired)
                    assert boundary.request.search is not None
                    state = advance(
                        DiscoveryState(
                            request=boundary.request.search, max_pages=1, max_articles=500
                        ),
                        parsed,
                    )
                    # The registered controlled corpus is exactly one exhausted page.
                    # No fabricated next URL, ignored conflict or truncated success.
                    if state.status != "completed" or state.reason != "reported_exhausted":
                        raise FetchDenied("controlled_provider_search_incomplete")
                    urls = [
                        catalog.for_article(registry, article).source_url
                        for article in parsed.articles
                    ]
                    boundary.check_current()
                    self.progress.discovery.commit(
                        lease.organization,
                        lease.job,
                        boundary.binding.discovery_revision,
                        SearchPage(
                            url=work.url,
                            digest=acquired.content_digest,
                            articles=urls,
                            reported_total=parsed.reported_total,
                            exhausted=True,
                            selector_valid=True,
                        ),
                    )
                    return self.progress.finish(work)
                registered = next(d for d in registry if d.source_url == work.url)
                observed = parse_response(
                    self.progress.settings, boundary, acquired, profile=registered.source_profile
                )
                binding, excerpts = self.xml.binding(
                    lease.organization, lease.job, boundary.binding.discovery_revision, work.url
                )
                retained = retain_xml(
                    observed.observation, binding, excerpts, registered=registered
                )
                boundary.require_response(observed.acquisition)
                existing = self.xml.commit_xml(lease.organization, lease.job, retained)
            if after_observation is not None:
                after_observation()
            batch = self.progress.associations.derive(
                lease.organization, lease.job, work.url, int(str(existing["revision"]))
            )
            return self.progress.finish(work, batch)
