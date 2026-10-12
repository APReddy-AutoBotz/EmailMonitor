"""Network-free shared acquisition plans; these are not permission grants or I/O.

A future protected transport must obtain actual DNS/peer/TLS evidence, keep the
connector behind its enforced boundary, and reauthorize at every named stage.
Public production acquisition remains unavailable; no fixture-private exception
or socket/resolver/browser implementation exists in this module.
"""

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin
from uuid import UUID

from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url, public_addresses
from emailmonitor.sources.policy import Operation


@dataclass(frozen=True)
class PlanScope:
    organization: UUID
    source: str
    policy_version: int
    operation: Operation
    allowed_hosts: frozenset[str]
    deadline: float
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if (
            type(self.organization) is not UUID
            or type(self.source) is not str
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", self.source) is None
            or type(self.policy_version) is not int
            or self.policy_version < 1
            or type(self.operation) is not Operation
            or type(self.allowed_hosts) is not frozenset
            or not 1 <= len(self.allowed_hosts) <= 16
            or any(type(host) is not str for host in self.allowed_hosts)
            or type(self.deadline) not in (int, float)
            or not math.isfinite(self.deadline)
            or self.deadline <= 0
            or type(self.max_redirects) is not int
            or not 0 <= self.max_redirects <= 5
        ):
            raise FetchDenied("plan_scope_denied")
        for host in self.allowed_hosts:
            if classify_url(f"https://{host}/", self.allowed_hosts).host != host:
                raise FetchDenied("plan_scope_denied")


@dataclass(frozen=True)
class HopPlan:
    scope: PlanScope
    url: SafeURL
    addresses: frozenset[str]
    selected_address: str
    history: tuple[str, ...]
    port: int = 443

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not PlanScope
            or type(self.url) is not SafeURL
            or type(self.addresses) is not frozenset
            or any(type(address) is not str for address in self.addresses)
            or type(self.selected_address) is not str
            or type(self.history) is not tuple
            or any(type(value) is not str for value in self.history)
            or type(self.port) is not int
            or self.port != 443
        ):
            raise FetchDenied("hop_plan_denied")
        if classify_url(self.url.normalized, self.scope.allowed_hosts) != self.url:
            raise FetchDenied("hop_plan_denied")
        if public_addresses(tuple(sorted(self.addresses))) != self.addresses:
            raise FetchDenied("hop_plan_denied")
        if self.selected_address not in self.addresses:
            raise FetchDenied("selected_address_denied")
        if (
            not 1 <= len(self.history) <= self.scope.max_redirects + 1
            or self.history[-1] != self.url.normalized
            or len(set(self.history)) != len(self.history)
        ):
            raise FetchDenied("redirect_history_denied")
        for value in self.history:
            if classify_url(value, self.scope.allowed_hosts).normalized != value:
                raise FetchDenied("redirect_history_denied")

    def validate_peer(self, peer: str) -> None:
        """Text invariant only; future transport must read the actual socket peer."""
        if public_addresses((peer,)) != frozenset({self.selected_address}):
            raise FetchDenied("connection_peer_denied")


class HopPlanner:
    def __init__(
        self,
        scope: PlanScope,
        authorize: Callable[[PlanScope, SafeURL], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(scope) is not PlanScope:
            raise FetchDenied("plan_scope_denied")
        self._scope, self._authorize, self._clock = scope, authorize, clock
        self.remaining()

    @property
    def scope(self) -> PlanScope:
        return self._scope

    def remaining(self) -> float:
        remaining = self.scope.deadline - self._clock()
        if not math.isfinite(remaining) or not 0 < remaining <= 60:
            raise FetchDenied("plan_deadline_denied")
        return remaining

    def authorize_url(self, value: str) -> SafeURL:
        """Called before resolution; grants no socket or cached authorization."""
        self.remaining()
        url = classify_url(value, self.scope.allowed_hosts)
        self._authorize(self.scope, url)
        self.remaining()
        return url

    def snapshot(
        self,
        url: SafeURL,
        records: tuple[str, ...],
        selected_address: str | None = None,
    ) -> HopPlan:
        """Validate all A/AAAA records, then reauthorize after resolver latency."""
        if (
            type(url) is not SafeURL
            or classify_url(url.normalized, self.scope.allowed_hosts) != url
        ):
            raise FetchDenied("hop_plan_denied")
        self.remaining()
        if type(records) is not tuple or any(type(record) is not str for record in records):
            raise FetchDenied("dns_records_denied")
        addresses = public_addresses(records)
        selected = min(addresses) if selected_address is None else selected_address
        plan = HopPlan(self.scope, url, addresses, selected, (url.normalized,))
        self.before_connect(plan)
        return plan

    def _current(self, plan: HopPlan) -> None:
        if type(plan) is not HopPlan or plan.scope != self.scope:
            raise FetchDenied("plan_scope_mismatch")
        self.remaining()
        self._authorize(self.scope, plan.url)
        self.remaining()

    def before_connect(self, plan: HopPlan) -> float:
        self._current(plan)
        return self.remaining()

    def before_release(self, plan: HopPlan) -> None:
        self._current(plan)

    def redirect(self, plan: HopPlan, location: str) -> SafeURL:
        """Return a newly authorized URL; old DNS snapshots are never reused."""
        self._current(plan)
        if len(plan.history) > self.scope.max_redirects:
            raise FetchDenied("redirect_limit_denied")
        if (
            type(location) is not str
            or not location
            or len(location) > 2048
            or "\\" in location
            or any(ord(character) <= 32 or ord(character) == 127 for character in location)
        ):
            raise FetchDenied("redirect_shape_denied")
        url = self.authorize_url(urljoin(plan.url.normalized, location))
        if url.normalized in plan.history:
            raise FetchDenied("redirect_loop_denied")
        return url

    def redirected_snapshot(
        self,
        previous: HopPlan,
        location: str,
        records: tuple[str, ...],
        selected_address: str | None = None,
    ) -> HopPlan:
        url = self.redirect(previous, location)
        fresh = self.snapshot(url, records, selected_address)
        return HopPlan(
            self.scope,
            fresh.url,
            fresh.addresses,
            fresh.selected_address,
            previous.history + (url.normalized,),
        )
