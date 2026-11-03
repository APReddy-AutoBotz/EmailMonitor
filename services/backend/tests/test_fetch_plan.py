"""Network-free planning invariants, not actual DNS/peer/TLS or egress acceptance."""

import socket
from dataclasses import FrozenInstanceError, replace
from typing import Any, cast
from uuid import UUID

import pytest
from emailmonitor.fetching.plan import HopPlanner, PlanScope
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.sources.policy import Operation

HOST = "synthetic.publisher.example"
URL = f"https://{HOST}/article-a.html"
PUBLIC4 = "8.8.8.8"
PUBLIC6 = "2001:4860:4860::8888"


def scope(**overrides: Any) -> PlanScope:
    values: dict[str, Any] = {
        "organization": UUID("11111111-1111-4111-8111-111111111111"),
        "source": "synthetic-publisher",
        "policy_version": 1,
        "operation": Operation.HTML,
        "allowed_hosts": frozenset({HOST}),
        "deadline": 150.0,
    }
    values.update(overrides)
    return PlanScope(**values)


def planner(value: PlanScope | None = None) -> HopPlanner:
    return HopPlanner(scope() if value is None else value, lambda bound, url: None, lambda: 100.0)


def test_shared_plan_is_network_free_and_binds_full_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Planning must never open a socket or resolve DNS")

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, forbidden)
    calls: list[tuple[PlanScope, SafeURL]] = []
    context = scope(operation=Operation.BROWSER)
    shared = HopPlanner(context, lambda bound, url: calls.append((bound, url)), lambda: 100.0)
    url = shared.authorize_url(URL)
    plan = shared.snapshot(url, (PUBLIC4, PUBLIC6), PUBLIC6)
    assert plan.scope == context and plan.url == url
    assert plan.addresses == frozenset({PUBLIC4, PUBLIC6})
    assert plan.selected_address == PUBLIC6 and plan.port == 443
    assert plan.history == (URL,) and shared.before_connect(plan) == 50
    plan.validate_peer(PUBLIC6)
    shared.before_release(plan)
    assert len(calls) == 4 and all(bound == context for bound, _ in calls)
    with pytest.raises(FrozenInstanceError):
        attribute = "selected_address"
        setattr(plan, attribute, PUBLIC4)
    with pytest.raises(FrozenInstanceError):
        attribute = "policy_version"
        setattr(context, attribute, 2)
    with pytest.raises(AttributeError):
        attribute = "scope"
        setattr(shared, attribute, scope(deadline=151))


@pytest.mark.parametrize(
    "records",
    [
        (),
        (PUBLIC4, "127.0.0.1"),
        (PUBLIC4, "10.0.0.1"),
        (PUBLIC4, "169.254.169.254"),
        (PUBLIC4, "::1"),
        (PUBLIC6, "fc00::1"),
        (PUBLIC6, "fe80::1"),
        (PUBLIC6, "::ffff:8.8.8.8"),
        (PUBLIC6, "2002:0808:0808::1"),
        ("bad",),
        tuple([PUBLIC4] * 33),
    ],
)
def test_entire_dns_snapshot_denied_without_selection_fallback(records: tuple[str, ...]) -> None:
    shared = planner()
    with pytest.raises(FetchDenied):
        shared.snapshot(shared.authorize_url(URL), records)


def test_selected_literal_must_belong_to_snapshot_and_actual_text_peer_must_match() -> None:
    shared = planner()
    url = shared.authorize_url(URL)
    with pytest.raises(FetchDenied, match="selected"):
        shared.snapshot(url, (PUBLIC4,), "1.1.1.1")
    plan = shared.snapshot(url, (PUBLIC4, "1.1.1.1"), PUBLIC4)
    for peer in ("1.1.1.1", "127.0.0.1", "::1", "bad"):
        with pytest.raises(FetchDenied):
            plan.validate_peer(peer)
    for port in (80, 444, True):
        with pytest.raises(FetchDenied):
            replace(plan, port=port)
    with pytest.raises(FetchDenied):
        replace(plan, addresses=frozenset({PUBLIC4, "127.0.0.1"}))
    with pytest.raises(FetchDenied):
        replace(plan, url=SafeURL(URL, "denied.fixture.example", "/article-a.html"))
    with pytest.raises(FetchDenied):
        shared.snapshot(cast(SafeURL, URL), (PUBLIC4,))
    with pytest.raises(FetchDenied):
        shared.snapshot(url, cast(tuple[str, ...], [PUBLIC4]))


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_version": 0},
        {"policy_version": True},
        {"source": "https://secret.example"},
        {"organization": "wrong"},
        {"operation": "browser"},
        {"allowed_hosts": frozenset()},
        {"allowed_hosts": frozenset({"127.0.0.1"})},
        {"allowed_hosts": frozenset({"evil.example/path"})},
        {"allowed_hosts": frozenset({"EXAMPLE.COM"})},
        {"deadline": float("nan")},
        {"deadline": float("inf")},
        {"deadline": True},
        {"max_redirects": -1},
        {"max_redirects": 6},
        {"max_redirects": True},
    ],
)
def test_untrusted_scope_shape_cannot_weaken_plan_limits(changes: dict[str, object]) -> None:
    with pytest.raises(FetchDenied):
        scope(**changes)


def test_one_absolute_deadline_is_preserved_across_stages_and_redirects() -> None:
    now = [100.0]
    shared = HopPlanner(scope(deadline=101), lambda bound, url: None, lambda: now[0])
    initial = shared.snapshot(shared.authorize_url(URL), (PUBLIC4,))
    now[0] = 100.5
    second = shared.redirected_snapshot(initial, "/article-b.html", (PUBLIC6,), PUBLIC6)
    assert second.scope.deadline == 101 and shared.remaining() == 0.5
    now[0] = 101
    for operation in (
        lambda: shared.authorize_url(URL),
        lambda: shared.before_connect(second),
        lambda: shared.before_release(second),
        lambda: shared.redirect(second, "/article-a.html"),
    ):
        with pytest.raises(FetchDenied, match="deadline"):
            operation()
    for deadline in (100, 99, 161):
        with pytest.raises(FetchDenied, match="deadline"):
            planner(scope(deadline=deadline))


def test_authorization_is_fresh_after_resolution_before_connection_and_release() -> None:
    allowed = [True]
    calls: list[str] = []

    def authorize(bound: PlanScope, url: SafeURL) -> None:
        calls.append(url.path)
        if not allowed[0]:
            raise FetchDenied("source_policy_denied")

    shared = HopPlanner(scope(), authorize, lambda: 100.0)
    url = shared.authorize_url(URL)
    allowed[0] = False
    with pytest.raises(FetchDenied, match="policy"):
        shared.snapshot(url, (PUBLIC4,))
    allowed[0] = True
    plan = shared.snapshot(url, (PUBLIC4,))
    allowed[0] = False
    for operation in (
        lambda: shared.before_connect(plan),
        lambda: shared.before_release(plan),
        lambda: shared.redirect(plan, "/article-b.html"),
    ):
        with pytest.raises(FetchDenied, match="policy"):
            operation()
    assert len(calls) == 6


def test_mismatched_tenant_source_version_operation_or_deadline_plan_denied() -> None:
    shared = planner()
    for changes in (
        {"organization": UUID("22222222-2222-4222-8222-222222222222")},
        {"source": "other-source"},
        {"policy_version": 2},
        {"operation": Operation.BROWSER},
        {"deadline": 149},
        {"allowed_hosts": frozenset({HOST, "other.fixture.example"})},
    ):
        other = planner(scope(**changes))
        plan = other.snapshot(other.authorize_url(URL), (PUBLIC4,))
        with pytest.raises(FetchDenied, match="mismatch"):
            shared.before_connect(plan)
        with pytest.raises(FetchDenied, match="mismatch"):
            shared.before_release(plan)


def test_redirect_uses_new_snapshot_same_scope_and_bounded_history() -> None:
    shared = planner(scope(max_redirects=1))
    first = shared.snapshot(shared.authorize_url(URL), (PUBLIC4,))
    second = shared.redirected_snapshot(first, "/article-b.html", (PUBLIC6,))
    assert second.scope == first.scope
    assert second.addresses == frozenset({PUBLIC6}) and second.selected_address == PUBLIC6
    assert second.history == (URL, f"https://{HOST}/article-b.html")
    with pytest.raises(FetchDenied, match="limit"):
        shared.redirect(second, "/no-contact.html")
    with pytest.raises(FetchDenied):
        shared.redirected_snapshot(first, "/article-b.html", (PUBLIC4, "127.0.0.1"))
    with pytest.raises(FetchDenied, match="loop"):
        shared.redirect(first, URL)


@pytest.mark.parametrize(
    "location",
    [
        "https://denied.fixture.example/x",
        "https://127.0.0.1/x",
        "https://user:pass@synthetic.publisher.example/x",
        "http://synthetic.publisher.example/x",
        "https://synthetic.publisher.example:444/x",
        " /article-b.html",
        "/article-\nb.html",
        "\\\\evil.example/x",
        "",
        "x" * 2049,
    ],
)
def test_redirect_url_refuses_scope_credentials_schemes_ports_and_ambiguous_shape(
    location: str,
) -> None:
    shared = planner()
    first = shared.snapshot(shared.authorize_url(URL), (PUBLIC4,))
    with pytest.raises(FetchDenied):
        shared.redirect(first, location)
