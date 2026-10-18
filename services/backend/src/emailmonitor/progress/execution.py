"""Trusted application execution composition; never selected by a message body.

The same dispatcher is used after the normal durable claim. Deployments may supply
an executor factory as Python composition only. The existing fixture services and
provider binding still independently enforce their current configuration/authority;
registering a factory does not enable live sources or grant a source permission.
"""

from collections.abc import Callable
from typing import Protocol

from emailmonitor.progress.provider import ProviderDispatch, ProviderJourney
from emailmonitor.progress.service import Progress, Work
from emailmonitor.progress.tooltip import TOOLTIP_URL, TooltipDispatch, TooltipJourney
from emailmonitor.sources.provider_documents import URLS


class Executor(Protocol):
    def process(
        self, work: Work, *, after_observation: Callable[[], None] | None = None
    ) -> str: ...


type ExecutorFactory = Callable[[Progress], Executor]


class ExecutionDispatcher:
    def __init__(
        self,
        progress: Progress,
        provider: ProviderDispatch | None = None,
        *,
        tooltip: TooltipDispatch | None = None,
    ) -> None:
        self.progress = progress
        self.tooltip = TooltipJourney(progress, tooltip) if tooltip is not None else None
        self.provider = ProviderJourney(progress, provider) if provider is not None else None

    def process(self, work: Work, *, after_observation: Callable[[], None] | None = None) -> str:
        # Only a server-claimed Work can reach here from broker.process. Never
        # infer a transport from a caller's URL, import path, headers or credentials.
        if self.provider is not None and work.url in URLS:
            return self.provider.process(work, after_observation=after_observation)
        if self.tooltip is not None and work.kind == "article" and work.url == TOOLTIP_URL:
            return self.tooltip.process(work, after_observation=after_observation)
        # Default is unchanged, including explicit refusal of provider URLs.
        # Provider exceptions deliberately cannot fall back to authored fixture bytes.
        return self.progress.process_fixture(work, after_observation)
