"""Trusted per-hop resource contract; admission never supplies network permission."""

from typing import Protocol

from emailmonitor.fetching.safety import SafeURL
from emailmonitor.sources.policy import Operation


class HopResources(Protocol):
    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object: ...

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None: ...
