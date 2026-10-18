"""Explicit trusted tooltip composition, never a message-selected browser permission.

The dispatch is responsible for the existing protected browser boundary. A context
row is current SQL metadata, not an authorization token or a transport grant.
"""

from collections.abc import Callable
from typing import Protocol

from emailmonitor.extraction.fixture import DIGESTS
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress, Work

TOOLTIP_URL = "https://synthetic.publisher.example/tooltip.html"


class TooltipDispatch(Protocol):
    def acquire(
        self, progress: Progress, work: Work, *, context: dict[str, object]
    ) -> ArticleObservation: ...


class TooltipJourney:
    def __init__(self, progress: Progress, dispatch: TooltipDispatch) -> None:
        self.progress, self.dispatch = progress, dispatch

    def _allow_browser(self, work: Work) -> bool:
        lease = work.lease
        with self.progress.extraction.discovery._tenant(
            lease.organization, Capability.ACQUIRE_SOURCE
        ) as (connection, _):
            parent = Ledger._lock(connection, lease.organization, lease.job)
            return JobRequest.model_validate(parent["request"]).options.allow_browser

    def process(self, work: Work, *, after_observation: Callable[[], None] | None = None) -> str:
        if work.kind != "article" or work.url != TOOLTIP_URL:
            raise FetchDenied("controlled_tooltip_route_denied")
        if after_observation is not None and not callable(after_observation):
            raise TypeError("Trusted completion callback required")
        lease = work.lease
        with bound(lease):
            extraction = self.progress.extraction
            context = extraction.prepare(lease.organization, lease.job, work.url)
            existing = next(
                (
                    r
                    for r in extraction.read(lease.organization, lease.job)
                    if r["article_url"] == work.url
                ),
                None,
            )
            if existing is None:
                # Keep the truthful unresolved static receipt even if the isolated
                # browser later refuses or crashes. Never derive a fallback success.
                existing = extraction.fixture(
                    lease.organization, lease.job, work.url, int(str(context["revision"]))
                )
            previous = ArticleObservation.model_validate(existing["observation"])
            if previous.route == "browser_dom" and previous.status == "observed":
                # Recovery still needs current browser permission; committed evidence
                # avoids repeating I/O, not the current tenant/policy/lease fences.
                extraction.prepare(lease.organization, lease.job, work.url, browser=True)
            elif self._allow_browser(work):
                if previous.status != "requires_browser":
                    raise FetchDenied("controlled_tooltip_observation_denied")
                context = extraction.prepare(lease.organization, lease.job, work.url, browser=True)
                observed = ArticleObservation.model_validate(
                    self.dispatch.acquire(self.progress, work, context=context)
                )
                if (
                    observed.url != TOOLTIP_URL
                    or observed.route != "browser_dom"
                    or observed.status != "observed"
                ):
                    raise FetchDenied("controlled_tooltip_observation_denied")
                existing = extraction.commit(
                    lease.organization,
                    lease.job,
                    observed,
                    expected_revision=int(str(context["revision"])),
                    source_digest=DIGESTS["tooltip.html"],
                )
            if after_observation is not None:
                after_observation()
            batch = self.progress.associations.derive(
                lease.organization, lease.job, work.url, int(str(existing["revision"]))
            )
            return self.progress.finish(work, batch)
