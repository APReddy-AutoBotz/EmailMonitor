import socket

import httpx
import pytest
from emailmonitor.config import Settings
from fixture_transport import HOST, PATHS, fixture_transport


def test_committed_fixture_bytes_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network access attempted")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    transport = fixture_transport(Settings(environment="test", fixture_mode=True))
    with httpx.Client(transport=transport, trust_env=False) as client:
        for route, path in PATHS.items():
            assert client.get(f"https://{HOST}{route}").content == path.read_bytes()
    assert len(PATHS) == 6


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic.publisher.example/article-a.html",
        "https://evil.example/article-a.html",
        "https://127.0.0.1/article-a.html",
        "https://synthetic.publisher.example:8443/article-a.html",
        "https://user:password@synthetic.publisher.example/article-a.html",
        "https://synthetic.publisher.example/article-a.html?token=secret",
        "https://synthetic.publisher.example/unknown",
        "https://synthetic.publisher.example/../README.md",
    ],
)
def test_fixture_transport_has_no_unrestricted_fallback(url: str) -> None:
    with httpx.Client(
        transport=fixture_transport(Settings(environment="test", fixture_mode=True))
    ) as client:
        with pytest.raises(ValueError):
            client.get(url)


def test_fixture_transport_requires_test_mode() -> None:
    for settings in (Settings(), Settings(environment="test")):
        with pytest.raises(ValueError):
            fixture_transport(settings)
