"""OA-027: Europe PMC live connector over recorded synthetic responses (no network).

Acceptance items from document 90: exact URL grammar, no request to hosts named in
response bodies, back-off and stop behaviour, approval bounds, and byte-identical
results between the live code path (replayed) and the offline fixture gateway.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from emailmonitor.discovery.openaccess_live import live_europe_pmc_orchestrator
from emailmonitor.discovery.openaccess_orchestrator import OpenAccessOrchestrator, RequestedSource
from emailmonitor.fetching.europepmc import EuropePmcFixtureGateway, EuropePmcRequest
from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url
from emailmonitor.sources.europepmc_live import (
    EuropePmcLiveGateway,
    LiveSourceApproval,
    SourceThrottle,
    TransportReply,
)
from emailmonitor.sources.europepmc_search import EuropePmcSearchRequest, doi_lookup_request
from emailmonitor.sources.openaccess import PmcIdentifier
from emailmonitor.sources.policy import Limits, Operation

ROOT = Path(__file__).resolve().parents[3]
JATS = ROOT / "fixtures" / "jats"
HOSTS = frozenset({"www.ebi.ac.uk"})
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def approval(**overrides: object) -> LiveSourceApproval:
    values: dict[str, object] = {
        "source": "europe_pmc",
        "purpose": "academic_contact_research",
        "permission_reference": "owner-decision-2026-11-19",
        "valid_until": NOW + timedelta(days=30),
        "limits": Limits(
            max_concurrent_requests=1, min_request_interval_seconds=5, max_articles_per_job=100
        ),
    }
    values.update(overrides)
    return LiveSourceApproval(**values)  # type: ignore[arg-type]


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def search_body(hits: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"hitCount": len(hits), "resultList": {"result": hits}, "nextCursorMark": None}
    ).encode()


class ReplayTransport:
    """Recorded synthetic responses keyed by request kind. Records every URL asked for."""

    def __init__(
        self,
        search: bytes | None = None,
        full_text: dict[str, TransportReply] | None = None,
        default: TransportReply | None = None,
    ) -> None:
        self.search = search
        self.full_text = full_text
        self.default = default
        self.requests: list[tuple[SafeURL, Operation, int]] = []

    def get(self, url: SafeURL, operation: Operation, max_bytes: int) -> TransportReply:
        self.requests.append((url, operation, max_bytes))
        if self.default is not None:
            return self.default
        if operation is Operation.SEARCH and self.search is not None:
            return TransportReply(200, "application/json", self.search, 10)
        if operation is Operation.XML:
            pmcid = url.path.split("/")[-2]
            if self.full_text is not None and pmcid in self.full_text:
                return self.full_text[pmcid]
            name = EuropePmcFixtureGateway._FIXTURE_MAP.get(pmcid)
            if name:
                return TransportReply(200, "text/xml", (JATS / name).read_bytes(), 10)
        return TransportReply(404, "text/plain", b"not found", 5)


def gateway(
    transport: ReplayTransport, clock: FakeClock | None = None, **kwargs: object
) -> EuropePmcLiveGateway:
    clock = clock or FakeClock()
    return EuropePmcLiveGateway(
        approval(**kwargs),
        transport,
        throttle=SourceThrottle(5, clock=clock, sleep=clock.sleep),
        now=lambda: NOW,
        clock=clock,
    )


def live(transport: ReplayTransport) -> OpenAccessOrchestrator:
    clock = FakeClock()
    orchestrator, _ = live_europe_pmc_orchestrator(
        approval(valid_until=datetime.now(UTC) + timedelta(days=30)),
        transport,
        reference_year=2026,
        throttle=SourceThrottle(5, clock=clock, sleep=clock.sleep),
    )
    return orchestrator


# ------------------------------------------------------------------ URL grammar


@pytest.mark.parametrize(
    "request_",
    [
        EuropePmcSearchRequest(query="crispr base editing"),
        EuropePmcSearchRequest(query='"gene therapy" AND (mouse OR rat)', page_size=100),
        EuropePmcSearchRequest(query="x", from_year=2020, until_year=2025, cursor_mark="AoE/x+="),
        doi_lookup_request("10.1371/journal.pbio.3002145"),
    ],
)
def test_planner_search_urls_pass_the_exact_grammar(request_: EuropePmcSearchRequest) -> None:
    url = request_.plan_url()
    safe = classify_url(url, HOSTS)
    assert safe.normalized == url
    assert safe.path.startswith("/europepmc/webservices/rest/search?")


def test_full_text_url_passes_without_query() -> None:
    request = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    assert classify_url(request.url, HOSTS).normalized == request.url


BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
GOOD = "query=crispr&format=json&resultType=lite&pageSize=25&cursorMark=%2A"


@pytest.mark.parametrize(
    "url",
    [
        BASE + GOOD + "&synonym=true",  # extra parameter
        BASE + "format=json&query=crispr&resultType=lite&pageSize=25&cursorMark=%2A",  # order
        BASE + GOOD.replace("json", "xml"),
        BASE + GOOD.replace("lite", "core"),
        BASE + GOOD.replace("pageSize=25", "pageSize=101"),
        BASE + GOOD.replace("pageSize=25", "pageSize=0"),
        BASE + GOOD.replace("pageSize=25", "pageSize=025"),
        BASE + GOOD.replace("query=crispr", "query=crispr%20editing"),  # non-canonical space
        BASE + GOOD.replace("query=crispr", "query="),
        BASE + GOOD.replace("query=crispr", "query=a%0Ab"),
        BASE + GOOD.replace("cursorMark=%2A", "cursorMark=%3Cx%3E"),
        BASE + GOOD + "&query=again",
        BASE + GOOD + "#frag",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/searchX?" + GOOD,
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML?" + GOOD,
        "https://www.ebi.ac.uk:8443/europepmc/webservices/rest/search?" + GOOD,
        "http://www.ebi.ac.uk/europepmc/webservices/rest/search?" + GOOD,
    ],
)
def test_any_other_query_shape_is_refused(url: str) -> None:
    with pytest.raises(FetchDenied):
        classify_url(url, HOSTS)


def test_grammar_does_not_open_other_hosts() -> None:
    with pytest.raises(FetchDenied, match="url_scope_denied"):
        classify_url(BASE.replace("www.ebi.ac.uk", "evil.example") + GOOD, HOSTS | {"evil.example"})
    with pytest.raises(FetchDenied):
        classify_url(BASE + GOOD, frozenset({"synthetic.publisher.example"}))


# --------------------------------------------------------- replay equivalence


@pytest.mark.parametrize("pmcid", sorted(EuropePmcFixtureGateway._FIXTURE_MAP))
def test_live_path_replay_matches_offline_fixture_path(pmcid: str) -> None:
    offline = OpenAccessOrchestrator(reference_year=2026).discover_and_extract(pmcid)
    transport = ReplayTransport()
    replayed = live(transport).discover_and_extract(pmcid)
    assert [c.model_dump() for c in replayed.contacts_extracted] == [
        c.model_dump() for c in offline.contacts_extracted
    ]
    assert [a.model_dump() for a in replayed.articles] == [a.model_dump() for a in offline.articles]
    assert [(u.host, op) for u, op, _ in transport.requests] == [("www.ebi.ac.uk", Operation.XML)]


def test_keyword_search_requests_only_planner_urls_never_body_links() -> None:
    hits: list[dict[str, object]] = [
        {
            "id": "1",
            "source": "MED",
            "pmcid": "PMC10293847",
            "isOpenAccess": "Y",
            "inEPMC": "Y",
            "title": "Synthetic CRISPR paper https://evil.example/steal",
            "fullTextUrlList": {"fullTextUrl": [{"url": "https://evil.example/pdf"}]},
        },
        {"id": "2", "source": "MED", "pmcid": "PMC5550001", "isOpenAccess": "Y", "inEPMC": "Y"},
        {"id": "3", "source": "MED", "pmcid": "PMC1234567", "isOpenAccess": "N", "inEPMC": "N"},
    ]
    transport = ReplayTransport(search=search_body(hits))
    result = live(transport).discover_and_extract("crispr", source="europe-pmc", max_results=5)
    hosts = {u.host for u, _, _ in transport.requests}
    assert hosts == {"www.ebi.ac.uk"}
    search_url = transport.requests[0][0]
    assert parse_qs(urlsplit(search_url.normalized).query)["query"] == [
        "(crispr) AND OPEN_ACCESS:y AND IN_EPMC:y"
    ]
    # Non-OA hit is never fetched; the 404 article is reported, not invented.
    fetched = [u.path.split("/")[-2] for u, op, _ in transport.requests if op is Operation.XML]
    assert fetched == ["PMC10293847", "PMC5550001"]
    status = {a.work_key: a.status for a in result.articles}
    assert status["PMC5550001"] == "full_text_unavailable"
    assert result.contacts_extracted


# ------------------------------------------------------- back-off and stopping


def test_throttle_enforces_policy_interval_between_requests() -> None:
    clock = FakeClock()
    gw = gateway(ReplayTransport(), clock)
    request = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    gw.fetch(request)
    gw.fetch(request)
    clock.t += 7
    gw.fetch(request)
    assert clock.slept == [5.0]
    assert gw.requests_made == 3


def test_throttle_below_policy_floor_is_refused() -> None:
    with pytest.raises(FetchDenied, match="throttle_interval_below_policy_floor"):
        SourceThrottle(1)
    clock = FakeClock()
    slow = approval(
        limits=Limits(
            max_concurrent_requests=1, min_request_interval_seconds=10, max_articles_per_job=10
        )
    )
    with pytest.raises(FetchDenied, match="throttle_interval_below_policy_floor"):
        EuropePmcLiveGateway(
            slow, ReplayTransport(), throttle=SourceThrottle(5, clock=clock), now=lambda: NOW
        )


@pytest.mark.parametrize(
    ("retry_after", "expected"), [(None, 5.0), (2.0, 5.0), (30.0, 30.0), (1e9, 3600.0)]
)
def test_rate_limit_backs_off_without_retrying(retry_after: float | None, expected: float) -> None:
    clock = FakeClock()
    transport = ReplayTransport(default=TransportReply(429, "text/plain", b"", 1, retry_after))
    gw = gateway(transport, clock)
    request = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    with pytest.raises(FetchDenied, match="europe_pmc_rate_limited"):
        gw.fetch(request)
    with pytest.raises(FetchDenied, match="europe_pmc_backoff_active"):
        gw.fetch(request)
    assert len(transport.requests) == 1
    clock.t += expected - 0.001
    with pytest.raises(FetchDenied, match="europe_pmc_backoff_active"):
        gw.fetch(request)
    clock.t += 0.002
    transport.default = None
    gw.fetch(request)
    assert len(transport.requests) == 2


@pytest.mark.parametrize("status", [401, 403])
def test_access_refusal_stops_the_source_for_the_run(status: int) -> None:
    transport = ReplayTransport(default=TransportReply(status, "text/html", b"blocked", 1))
    clock = FakeClock()
    orchestrator, gw = live_europe_pmc_orchestrator(
        approval(valid_until=datetime.now(UTC) + timedelta(days=30)),
        transport,
        throttle=SourceThrottle(5, clock=clock, sleep=clock.sleep),
    )
    result = orchestrator.discover_and_extract("PMC10293847")
    assert result.articles[0].status == "failed"
    assert result.articles[0].reason == "europe_pmc_access_refused"
    with pytest.raises(FetchDenied, match="europe_pmc_source_stopped"):
        gw.fetch(EuropePmcRequest(pmcid=PmcIdentifier(value="PMC1234567")))
    assert len(transport.requests) == 1


def test_oversized_and_wrong_media_type_are_refused() -> None:
    request = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    big = ReplayTransport(default=TransportReply(200, "text/xml", b"x" * (4_194_304 + 1), 1))
    with pytest.raises(FetchDenied, match="europe_pmc_payload_too_large"):
        gateway(big).fetch(request)
    html = ReplayTransport(default=TransportReply(200, "text/html", b"<html/>", 1))
    with pytest.raises(FetchDenied, match="invalid_media_type_not_xml"):
        gateway(html).fetch(request)
    search = ReplayTransport(default=TransportReply(200, "text/html", b"{}", 1))
    with pytest.raises(FetchDenied, match="invalid_media_type_not_json"):
        gateway(search).search(EuropePmcSearchRequest(query="x"))


def test_transport_receives_the_policy_byte_ceiling() -> None:
    transport = ReplayTransport()
    gateway(transport).fetch(EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847")))
    assert transport.requests[0][2] == 4_194_304


# ------------------------------------------------------------------- approval


def test_missing_transport_is_refused() -> None:
    with pytest.raises(FetchDenied, match="live_transport_unavailable"):
        EuropePmcLiveGateway(approval(), None, now=lambda: NOW)


@pytest.mark.parametrize(
    "valid_until", [NOW - timedelta(seconds=1), NOW, NOW + timedelta(days=366)]
)
def test_approval_must_be_current_and_bounded(valid_until: datetime) -> None:
    with pytest.raises(FetchDenied, match="live_source_approval_invalid"):
        EuropePmcLiveGateway(approval(valid_until=valid_until), ReplayTransport(), now=lambda: NOW)


def test_approval_expiring_mid_run_stops_before_the_next_request() -> None:
    moment = [NOW]
    transport = ReplayTransport()
    clock = FakeClock()
    gw = EuropePmcLiveGateway(
        approval(valid_until=NOW + timedelta(minutes=1)),
        transport,
        throttle=SourceThrottle(5, clock=clock, sleep=clock.sleep),
        now=lambda: moment[0],
        clock=clock,
    )
    request = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    gw.fetch(request)
    moment[0] = NOW + timedelta(minutes=2)
    with pytest.raises(FetchDenied, match="live_source_approval_invalid"):
        gw.fetch(request)
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"valid_until": datetime(2026, 12, 1)},  # naive
        {"source": "openalex"},
        {"purpose": "marketing"},
        {"permission_reference": "has space"},
    ],
)
def test_approval_record_shape(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        approval(**overrides)


# --------------------------------------------------------- source isolation


def test_live_composition_never_answers_from_fixture_sources() -> None:
    transport = ReplayTransport(search=search_body([]))
    orchestrator = live(transport)
    merged = orchestrator.discover_and_extract("crispr", source="all")
    assert merged.source_errors == {
        "openalex": "source_not_enabled",
        "crossref": "source_not_enabled",
    }
    assert merged.articles == ()
    sources: tuple[RequestedSource, ...] = ("openalex", "crossref", "biorxiv")
    for source in sources:
        with pytest.raises(FetchDenied, match="source_not_enabled"):
            orchestrator.discover_and_extract("crispr", source=source)
    with pytest.raises(FetchDenied, match="source_not_enabled"):
        orchestrator.discover_and_extract("10.5555/x.1")  # auto routes a DOI to Crossref
    assert all(u.host == "www.ebi.ac.uk" for u, _, _ in transport.requests)


@pytest.mark.parametrize("enabled", [frozenset(), frozenset({"europe-pmc", "scihub"})])
def test_enabled_sources_must_be_known_and_non_empty(enabled: frozenset[str]) -> None:
    with pytest.raises(FetchDenied, match="enabled_sources_invalid"):
        OpenAccessOrchestrator(enabled_sources=enabled)  # type: ignore[arg-type]
