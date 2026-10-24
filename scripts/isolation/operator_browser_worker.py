"""Explicit synthetic tooltip composition, using a single owned isolated guest.

This acceptance-only adapter is not a production browser runtime. One guest may
make one attempt; a committed observation is replayed by the durable journey
without entering this adapter. Uncertain/failed guests cannot be restarted.
"""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.fetching.fixture import HOSTS, TenantFixtureAuthorization
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.jobs.broker import FixtureWorkerConfig
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress, Work
from emailmonitor.sources.policy import Operation
from operator_browser_timing import BrowserTiming, read_admission_timing
from operator_provider_worker import PipeOwner, controlled_worker
from run_browser_acceptance import conversation
from transport_rpc import BrowserProxyMediator, GatewayProxy, OwnedProcess
from transport_topology import docker

URL = "https://synthetic.publisher.example/tooltip.html"


class TooltipBrowser:
    def __init__(
        self, identifier: str, evidence: list[dict[str, Any]], timing: BrowserTiming | None = None
    ) -> None:
        if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Owned browser identifier required")
        self.identifier, self.evidence = identifier, evidence
        self.attempted = False
        self.timing = timing

    def state(self) -> dict[str, Any]:
        values = json.loads(docker("inspect", self.identifier, timeout=5).stdout)
        if len(values) != 1 or values[0]["Id"] != self.identifier:
            raise RuntimeError("Owned browser state could not be verified")
        return cast(dict[str, Any], values[0]["State"])

    def stopped(self, *, initial: bool = False) -> None:
        state = self.state()
        if (
            state["Running"]
            or state["OOMKilled"]
            or state["ExitCode"] != 0
            or state["Status"] != ("created" if initial else "exited")
        ):
            raise RuntimeError("Owned browser stopped state refused")

    def acquire(
        self, pipe: PipeOwner, progress: Progress, work: Work, *, context: dict[str, object]
    ) -> ArticleObservation:
        pipe.check()
        if self.attempted or pipe.poisoned or work.kind != "article" or work.url != URL:
            raise FetchDenied("controlled_tooltip_attempt_refused")
        self.stopped(initial=True)
        self.attempted = True
        version = int(str(context["policy_version"]))
        organization, job = work.lease.organization, work.lease.job
        allow = TenantFixtureAuthorization(
            progress.database, progress.token, organization, "synthetic-publisher", version
        )

        def current() -> None:
            pipe.check()
            row = progress.extraction.prepare(organization, job, URL, browser=True)
            pipe.check()
            if (
                row["source_id"] != "synthetic-publisher"
                or int(str(row["policy_version"])) != version
                or row["revision"] != context["revision"]
            ):
                raise FetchDenied("controlled_tooltip_authority_changed")

        def scope(operation: Operation) -> PlanScope:
            current()
            if operation != Operation.BROWSER:
                raise FetchDenied("controlled_tooltip_operation_refused")
            return PlanScope(
                organization,
                "synthetic-publisher",
                version,
                operation,
                HOSTS,
                time.monotonic() + 19,
                2,
            )

        def authorize(bound: PlanScope, url: SafeURL) -> None:
            current()
            if (
                url.normalized != URL
                or bound.organization != organization
                or bound.source != "synthetic-publisher"
                or bound.policy_version != version
                or bound.operation != Operation.BROWSER
            ):
                raise FetchDenied("controlled_tooltip_route_refused")
            allow(url, bound.operation)
            pipe.check()

        resources = allow.resources
        if self.timing is not None:

            def read_timing(ticket: object, deadline: float) -> dict[str, Any]:
                pipe.check()
                row = read_admission_timing(progress, organization, job, version, ticket, deadline)
                pipe.check()
                return dict(row)

            resources = self.timing.resources(resources, read_timing)
        target = GatewayProxy(cast(OwnedProcess, pipe), scope, authorize, resources=resources)
        mediator = BrowserProxyMediator(target)
        # Revocation covers the entire conversation, including SQL callbacks and
        # time between frames. The I/O lock itself never spans SQL or guest work.
        pipe.active = True
        try:
            current()
            result = conversation(self.identifier, mediator)
            self.stopped()
            current()
            article = ArticleObservation.model_validate(result.pop("article_observation"))
            self.evidence.append(
                {
                    **result,
                    "selected_peers": [list(peer) for peer in mediator.selected_peers],
                    "guest_stopped": True,
                }
            )
            return article
        except BaseException as error:
            pipe.poisoned = True
            try:
                # Only this exact already-owned synthetic guest is stopped.
                docker("stop", "--time", "1", self.identifier, timeout=10)
                if self.state()["Running"]:
                    raise RuntimeError("Owned browser remained running")
            except Exception:
                error.add_note("Owned browser stop unverified; topology cleanup still required")
            raise
        finally:
            pipe.active = False


class BoundTooltip:
    def __init__(self, browser: TooltipBrowser, pipe: PipeOwner) -> None:
        self.browser, self.pipe = browser, pipe

    def acquire(
        self, progress: Progress, work: Work, *, context: dict[str, object]
    ) -> ArticleObservation:
        return self.browser.acquire(self.pipe, progress, work, context=context)


@contextmanager
def browser_worker(
    config: FixtureWorkerConfig,
    gateway: OwnedProcess,
    browser_identifier: str,
    *,
    evidence: list[dict[str, Any]] | None = None,
    timing: BrowserTiming | None = None,
) -> Iterator[Any]:
    browser = TooltipBrowser(browser_identifier, evidence if evidence is not None else [], timing)
    with controlled_worker(
        config,
        gateway,
        lambda progress, pipe: ExecutionDispatcher(progress, tooltip=BoundTooltip(browser, pipe)),
    ) as app:
        yield app
