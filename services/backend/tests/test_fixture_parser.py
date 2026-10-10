from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.parsing.fixture import observe_fixture

SETTINGS = Settings(environment="test", fixture_mode=True)


def test_fixture_observations_are_inert_and_not_contact_extraction() -> None:
    payload = b'<p>synthetic</p><script>fetch("https://evil.example/")</script>'
    observation = observe_fixture(SETTINGS, payload)
    assert observation.visible_text == "synthetic"
    assert observation.tags == 2 and len(observation.digest) == 64
    assert not hasattr(observation, "authors") and not hasattr(observation, "emails")


def test_existing_synthetic_html_bytes_produce_only_visible_text_observation() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = (root / "fixtures/html/article-a.html").read_bytes()
    assert observe_fixture(SETTINGS, payload).visible_text


@pytest.mark.parametrize("payload", [b"x" * 65537, b"x" * 16385, b"<div>" * 65, b"\xff"])
def test_parse_caps_and_invalid_utf8_fail_closed(payload: bytes) -> None:
    with pytest.raises(FetchDenied):
        observe_fixture(SETTINGS, payload)


def test_byte_observer_cannot_activate_outside_explicit_test_mode() -> None:
    for settings in (Settings(), Settings(environment="test")):
        with pytest.raises(IsolationUnavailable):
            observe_fixture(settings, b"fixture")
