import socket
from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import (
    HOSTS,
    ByteResponse,
    FetchLimits,
    FixtureByteTransport,
    FixtureGateway,
    browser_request,
    live_fetch,
)
from emailmonitor.fetching.safety import ConnectionPlan, FetchDenied, classify_url, public_addresses
from emailmonitor.sources.policy import Operation

URL = "https://synthetic.publisher.example/article-a.html"
SETTINGS = Settings(environment="test", fixture_mode=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic.publisher.example/article-a.html",
        "file:///etc/passwd",
        "https://user:secret@synthetic.publisher.example/article-a.html",
        "https://synthetic.publisher.example:8443/article-a.html",
        "https://synthetic.publisher.example/article-a.html?token=secret",
        "https://synthetic.publisher.example/article-a.html?",
        " https://synthetic.publisher.example/article-a.html",
        "https://synthetic.publisher.example/art\ticle-a.html",
        "https://synthetic.publisher.example./article-a.html",
        "https://synthetic.publisher.example\\evil.example/article-a.html",
        "https://evilsynthetic.publisher.example/article-a.html",
        "https://synthetic.publisher.example/../article-a.html",
        "https://synthetic.publisher.example/%2e%2e/article-a.html",
        "https://synthetic.publisher.example/article-a.html#fragment",
        "https://[::1]/article-a.html",
        "https://127.0.0.1/article-a.html",
        "https://0177.0.0.1/article-a.html",
        "https://2130706433/article-a.html",
        "https://0x7f000001/article-a.html",
        "https://xn--/article-a.html",
        "https://例え.test/article-a.html",
        "https://[invalid/",
        "x" * 2049,
    ],
)
def test_url_classification_fails_closed(url: str) -> None:
    with pytest.raises(FetchDenied):
        classify_url(url, HOSTS)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "192.0.2.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:8.8.8.8",
        "2002:0808:0808::1",
        "fe80::1%eth0",
        "invalid",
    ],
)
def test_nonpublic_or_ambiguous_dns_record_blocks_whole_result(address: str) -> None:
    with pytest.raises(FetchDenied):
        public_addresses(("8.8.8.8", address))


def test_connection_pinning_contract_only() -> None:
    url = classify_url("https://source.example.test/article", frozenset({"source.example.test"}))
    plan = ConnectionPlan.from_records(url, ("8.8.8.8", "2001:4860:4860::8888"))
    plan.validate_peer("8.8.8.8", certificate_verified=True)
    for peer, certificate in (("127.0.0.1", True), ("1.1.1.1", True), ("8.8.8.8", False)):
        with pytest.raises(FetchDenied):
            plan.validate_peer(peer, certificate)
    with pytest.raises(FetchDenied):
        public_addresses(())


def test_fixture_bytes_have_no_dns_socket_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network attempted")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    payload = (Path(__file__).resolve().parents[3] / "fixtures/html/article-a.html").read_bytes()
    gateway = FixtureGateway(
        SETTINGS,
        FixtureByteTransport(
            SETTINGS, {URL: ByteResponse(200, (payload,), content_length=len(payload))}
        ),
        lambda url, operation: None,
    )
    assert gateway.fetch(URL) == payload
    with pytest.raises(FetchDenied):
        gateway.fetch(URL.replace("article-a", "unknown"))


@pytest.mark.parametrize(
    "response",
    [
        ByteResponse(401, ()),
        ByteResponse(403, ()),
        ByteResponse(429, ()),
        ByteResponse(500, ()),
        ByteResponse(200, (b"x",), content_type="application/pdf"),
        ByteResponse(200, (b"x",), content_encoding="gzip"),
        ByteResponse(200, (b"x",), content_length=100),
        ByteResponse(200, (b"12", b"345")),
    ],
)
def test_response_denial_never_retries_or_relaxes_limits(response: ByteResponse) -> None:
    calls: list[Operation] = []
    gateway = FixtureGateway(
        SETTINGS,
        FixtureByteTransport(SETTINGS, {URL: response}),
        lambda url, op: calls.append(op),
        FetchLimits(max_bytes=4),
    )
    with pytest.raises(FetchDenied):
        gateway.fetch(URL)
    assert calls == [Operation.HTML]


def test_every_redirect_and_release_reauthorizes_without_credentials() -> None:
    next_url = URL.replace("article-a", "article-b")
    calls: list[str] = []
    gateway = FixtureGateway(
        SETTINGS,
        FixtureByteTransport(
            SETTINGS,
            {
                URL: ByteResponse(302, (), location="/article-b.html"),
                next_url: ByteResponse(200, (b"fixture",)),
            },
        ),
        lambda url, op: calls.append(url.normalized),
    )
    assert gateway.fetch(URL) == b"fixture"
    assert calls == [URL, next_url, next_url]
    assert not hasattr(gateway._transport, "headers")
    for location in ("https://evil.example/secret", "http://127.0.0.1/", "/article-b.html?token=x"):
        transport = FixtureByteTransport(SETTINGS, {URL: ByteResponse(302, (), location=location)})
        with pytest.raises(FetchDenied):
            FixtureGateway(SETTINGS, transport, lambda url, op: None).fetch(URL)


def test_redirect_loop_budget_and_absolute_observed_deadline() -> None:
    loop = FixtureByteTransport(SETTINGS, {URL: ByteResponse(302, (), location=URL)})
    for count in (0, 5):
        with pytest.raises(FetchDenied):
            FixtureGateway(
                SETTINGS, loop, lambda url, op: None, FetchLimits(max_redirects=count)
            ).fetch(URL)
    times = iter((0.0, 0.0, 30.0, 60.0))
    response = FixtureByteTransport(SETTINGS, {URL: ByteResponse(200, (b"1", b"2"))})
    with pytest.raises(FetchDenied, match="deadline"):
        FixtureGateway(SETTINGS, response, lambda url, op: None, clock=lambda: next(times)).fetch(
            URL
        )


def test_permission_revocation_before_release_discards_bytes() -> None:
    calls = 0

    def authorize(url: object, operation: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FetchDenied("source_policy_denied")

    gateway = FixtureGateway(
        SETTINGS, FixtureByteTransport(SETTINGS, {URL: ByteResponse(200, (b"fixture",))}), authorize
    )
    with pytest.raises(FetchDenied):
        gateway.fetch(URL)


@pytest.mark.parametrize(
    "resource",
    [
        "document",
        "script",
        "iframe",
        "stylesheet",
        "image",
        "fetch",
        "websocket",
        "service_worker",
        "popup",
        "download",
    ],
)
def test_browser_and_live_entrypoints_remain_disabled(resource: str) -> None:
    with pytest.raises(FetchDenied, match="isolation"):
        browser_request(URL, resource)
    with pytest.raises(FetchDenied, match="unimplemented"):
        live_fetch(URL)


def test_test_transport_and_limits_cannot_activate_in_normal_runtime() -> None:
    for settings in (Settings(), Settings(environment="test")):
        with pytest.raises(FetchDenied):
            FixtureByteTransport(settings, {})
    for limit in ({"max_redirects": 6}, {"max_bytes": 5_242_881}, {"total_seconds": 61}):
        with pytest.raises(ValueError):
            FetchLimits(**limit)
