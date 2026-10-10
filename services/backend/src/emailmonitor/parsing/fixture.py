"""Bounded inert HTML observation, not academic contact/PDF extraction."""

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import FetchDenied


@dataclass(frozen=True)
class FixtureObservation:
    digest: str
    visible_text: str
    tags: int


class _Observer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.tags = 0
        self.characters = 0
        self.depth = 0
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags += 1
        self.depth += 1
        if self.tags > 2048 or self.depth > 64:
            raise FetchDenied("fixture_parse_limit_exceeded")
        if tag in ("script", "style"):
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.hidden_depth:
            self.hidden_depth -= 1
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.characters += len(data)
            if self.characters > 16384:
                raise FetchDenied("fixture_parse_limit_exceeded")
            self.text.append(data)


def observe_fixture(settings: Settings, payload: bytes) -> FixtureObservation:
    require_fixture(settings)
    if type(payload) is not bytes or len(payload) > 65536:
        raise FetchDenied("fixture_parse_limit_exceeded")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise FetchDenied("fixture_encoding_denied") from None
    observer = _Observer()
    observer.feed(text)
    observer.close()
    return FixtureObservation(
        hashlib.sha256(payload).hexdigest(), "".join(observer.text), observer.tags
    )
