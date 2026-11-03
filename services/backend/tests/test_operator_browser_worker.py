"""Owned browser adapter failure and authority tests; real guests run in CI."""

import threading
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import operator_browser_worker as module
import pytest
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.fetching.fixture import HOSTS
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.progress.service import Progress, Work
from emailmonitor.sources.policy import Operation
from operator_provider_worker import PipeOwner
from transport_rpc import OwnedProcess


@pytest.fixture
def owned(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    pipe = PipeOwner(cast(OwnedProcess, SimpleNamespace(poisoned=False)))
    pipe.owner = threading.get_ident()
    row = {"source_id": "synthetic-publisher", "policy_version": 7, "revision": 3}
    calls: list[object] = []
    states = [{"Running": False, "OOMKilled": False, "ExitCode": 0, "Status": "created"}]
    browser = module.TooltipBrowser("a" * 64, [])
    monkeypatch.setattr(browser, "state", lambda: states[-1])
    work = cast(
        Work,
        SimpleNamespace(
            kind="article", url=module.URL, lease=SimpleNamespace(organization=uuid4(), job=uuid4())
        ),
    )

    def prepare(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append("prepare")
        assert kwargs == {"browser": True}
        return dict(row)

    progress = cast(
        Progress,
        SimpleNamespace(
            database=object(), token="synthetic", extraction=SimpleNamespace(prepare=prepare)
        ),
    )

    class Authorization:
        def __init__(self, *args: object) -> None:
            assert args[-1] == 7
            self.resources = object()

        def __call__(self, url: object, operation: Operation) -> None:
            calls.append("authorized")
            assert operation == Operation.BROWSER

    proxies: list[SimpleNamespace] = []

    def proxy(process: object, scope: object, authorize: object, *, resources: object) -> object:
        assert process is pipe and resources is not None
        value = SimpleNamespace(scope=scope, authorize=authorize, resources=resources)
        proxies.append(value)
        return value

    monkeypatch.setattr(module, "TenantFixtureAuthorization", Authorization)
    monkeypatch.setattr(module, "GatewayProxy", proxy)
    monkeypatch.setattr(
        module,
        "BrowserProxyMediator",
        lambda target: SimpleNamespace(target=target, selected_peers=[]),
    )
    monkeypatch.setattr(module, "docker", lambda *args, **kwargs: calls.append("stop"))
    article = object()
    monkeypatch.setattr(ArticleObservation, "model_validate", lambda value: article)

    def conversation(identifier: str, mediator: Any) -> dict[str, object]:
        calls.append("conversation")
        assert pipe.active and identifier == browser.identifier
        scope = mediator.target.scope(Operation.BROWSER)
        assert scope.policy_version == 7
        mediator.target.authorize(scope, classify_url(module.URL, HOSTS))
        states.append({"Running": False, "OOMKilled": False, "ExitCode": 0, "Status": "exited"})
        return {"article_observation": {}, "diagnostic": "synthetic-browser-only"}

    monkeypatch.setattr(module, "conversation", conversation)
    return SimpleNamespace(
        pipe=pipe,
        browser=browser,
        work=work,
        progress=progress,
        row=row,
        calls=calls,
        states=states,
        proxies=proxies,
        article=article,
    )


def acquire(value: SimpleNamespace) -> object:
    return value.browser.acquire(value.pipe, value.progress, value.work, context=dict(value.row))


def test_current_server_policy_and_single_owned_attempt(owned: SimpleNamespace) -> None:
    assert acquire(owned) is owned.article
    assert owned.calls.count("conversation") == 1 and not owned.pipe.active
    assert owned.browser.evidence == [
        {"diagnostic": "synthetic-browser-only", "selected_peers": [], "guest_stopped": True}
    ]
    with pytest.raises(FetchDenied, match="attempt_refused"):
        acquire(owned)
    assert owned.calls.count("conversation") == 1


@pytest.mark.parametrize(
    "field,value", [("Running", True), ("OOMKilled", True), ("ExitCode", 1), ("Status", "exited")]
)
def test_unverified_initial_guest_never_starts(
    owned: SimpleNamespace, field: str, value: object
) -> None:
    owned.states[0][field] = value
    with pytest.raises(RuntimeError, match="stopped state refused"):
        acquire(owned)
    assert "conversation" not in owned.calls


@pytest.mark.parametrize("failure", ["conversation", "still_running", "revoked", "policy"])
def test_failure_poison_stop_and_no_success_evidence(
    owned: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def conversation(identifier: str, mediator: Any) -> dict[str, object]:
        assert owned.pipe.active
        if failure == "conversation":
            raise RuntimeError("Synthetic bounded failure")
        if failure == "revoked":
            owned.pipe.revoke()
        if failure == "policy":
            owned.row["policy_version"] = 8
        owned.states.append(
            {
                "Running": failure == "still_running",
                "OOMKilled": False,
                "ExitCode": 0,
                "Status": "exited",
            }
        )
        return {"article_observation": {}}

    monkeypatch.setattr(module, "conversation", conversation)
    with pytest.raises((RuntimeError, FetchDenied)):
        acquire(owned)
    assert owned.pipe.poisoned and not owned.pipe.active
    assert "stop" in owned.calls and owned.browser.evidence == []
    with pytest.raises((RuntimeError, FetchDenied)):
        acquire(owned)


@pytest.mark.parametrize("mismatch", ["url", "operation", "tenant", "version", "source"])
def test_authorization_rechecks_exact_bound_route(owned: SimpleNamespace, mismatch: str) -> None:
    acquire(owned)
    target = owned.proxies[0]
    base = target.scope(Operation.BROWSER)
    scope = PlanScope(
        uuid4() if mismatch == "tenant" else base.organization,
        "other" if mismatch == "source" else base.source,
        8 if mismatch == "version" else base.policy_version,
        Operation.HTML if mismatch == "operation" else base.operation,
        base.allowed_hosts,
        base.deadline,
        base.max_redirects,
    )
    url = module.URL.replace("tooltip", "article-first") if mismatch == "url" else module.URL
    with pytest.raises(FetchDenied, match="route_refused"):
        target.authorize(scope, classify_url(url, HOSTS))


def test_revocation_in_late_sql_callback_blocks_guest(owned: SimpleNamespace) -> None:
    def prepare(*args: object, **kwargs: object) -> dict[str, object]:
        owned.pipe.revoke()
        return dict(owned.row)

    owned.progress.extraction.prepare = prepare
    # current() must check ownership again after the callback, before guest I/O.
    with pytest.raises(RuntimeError, match="ownership refused"):
        acquire(owned)
    assert "conversation" not in owned.calls and owned.pipe.poisoned


def test_revocation_in_final_authorization_refuses_byte_release(
    owned: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RevokingAuthorization:
        def __init__(self, *args: object) -> None:
            self.resources = object()

        def __call__(self, url: object, operation: Operation) -> None:
            owned.pipe.revoke()

    monkeypatch.setattr(module, "TenantFixtureAuthorization", RevokingAuthorization)
    with pytest.raises(RuntimeError, match="ownership refused"):
        acquire(owned)
    assert owned.pipe.poisoned and owned.browser.evidence == []
    assert "stop" in owned.calls


@pytest.mark.parametrize("failure", ["none", "readiness", "revoke", "join", "queue"])
def test_shared_worker_bounded_teardown(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import nullcontext

    import operator_provider_worker as worker

    calls: list[object] = []
    state = SimpleNamespace(should_terminate="previous")

    class Thread:
        ident: int | None = None
        alive = False

        def __init__(self, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            self.ident = 1
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: int) -> None:
            calls.append(("join", timeout))
            self.alive = failure == "join"

    class Event:
        def set(self) -> None:
            pass

        def wait(self, timeout: int) -> bool:
            calls.append(("ready", timeout))
            return failure != "readiness"

    class Pipe:
        def __init__(self, process: object) -> None:
            pass

        def revoke(self) -> None:
            calls.append("revoke")
            if failure == "revoke":
                raise RuntimeError("revoke failed")

    def delete(**kwargs: object) -> None:
        calls.append("delete")
        if failure == "queue":
            raise RuntimeError("queue failed")

    channel = SimpleNamespace(
        queue_delete=delete, exchange_delete=delete, close=lambda: calls.append("channel closed")
    )
    app = SimpleNamespace(
        finalize=lambda: calls.append("finalize"),
        WorkController=lambda **kwargs: SimpleNamespace(start=lambda: None),
        connection_for_write=lambda: nullcontext(SimpleNamespace(channel=lambda: channel)),
        close=lambda: calls.append("app closed"),
    )
    ledger = SimpleNamespace(
        database=SimpleNamespace(
            engine=SimpleNamespace(dispose=lambda: calls.append("database disposed"))
        )
    )
    monkeypatch.setattr(worker, "create_worker", lambda *args, **kwargs: (app, ledger))
    monkeypatch.setattr(worker, "import_module", lambda name: state)
    monkeypatch.setattr(worker, "PipeOwner", Pipe)
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(threading, "Event", Event)
    config = SimpleNamespace(queue="em-fixture-owned-browser")

    def run() -> None:
        with worker.controlled_worker(cast(Any, config), cast(Any, object()), cast(Any, None)):
            calls.append("yielded")

    if failure == "none":
        run()
    else:
        with pytest.raises(RuntimeError):
            run()
    assert ("ready", 20) in calls and ("join", 150) in calls
    assert calls.index("revoke") < calls.index(("join", 150))
    assert ("yielded" in calls) is (failure != "readiness")
    if failure == "join":
        assert state.should_terminate == 0
        assert "app closed" not in calls and "database disposed" not in calls
    else:
        assert state.should_terminate == "previous"
        assert calls[-2:] == ["app closed", "database disposed"]


@pytest.mark.parametrize("missing", [False, True])
def test_optional_timing_read_is_exact_tenant_and_never_loses_ticket(
    owned: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    import time
    from contextlib import contextmanager

    from emailmonitor.administration.source import SourceLease
    from emailmonitor.organizations.roles import Capability
    from operator_browser_timing import BrowserTiming
    from sqlalchemy.exc import NoResultFound

    org, job = owned.work.lease.organization, owned.work.lease.job
    ticket = SourceLease(uuid4(), uuid4(), org)
    finished: list[object] = []
    queries: list[tuple[str, dict[str, object]]] = []

    class Connection:
        def execute(self, query: object, parameters: dict[str, object]) -> Any:
            queries.append((str(query), parameters))
            return self

        def mappings(self) -> Any:
            return self

        def one(self) -> dict[str, object]:
            if missing:
                raise NoResultFound("Missing/expired/mismatched authorized observation")
            return {"attempts": 1, "admitted": 100.0}

    @contextmanager
    def tenant(authority: object, organization: object, capability: object) -> Any:
        assert (authority, organization, capability) == (
            "synthetic",
            org,
            Capability.ACQUIRE_SOURCE,
        )
        yield Connection(), None

    owned.progress.database = SimpleNamespace(tenant=tenant)
    owned.browser.timing = BrowserTiming()

    class Authorization:
        def __init__(self, *args: object) -> None:
            self.resources = SimpleNamespace(
                acquire=lambda *args: ticket,
                finish=lambda value, status, retry: finished.append(value),
            )

        def __call__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(module, "TenantFixtureAuthorization", Authorization)
    original = module.__dict__["conversation"]

    def conversation(identifier: str, mediator: Any) -> dict[str, object]:
        result = original(identifier, mediator)
        resources = mediator.target.resources
        actual = resources.acquire(
            classify_url(module.URL, HOSTS), Operation.BROWSER, time.monotonic() + 10
        )
        assert actual is ticket
        resources.finish(actual, 200, "")
        return cast(dict[str, object], result)

    monkeypatch.setattr(module, "conversation", conversation)
    assert acquire(owned) is owned.article
    assert finished == [ticket]
    assert queries[1][1] == {"org": org, "ticket": ticket.identifier, "job": job, "version": 7}
    assert "nonce" not in queries[1][0] and "r.path" not in queries[1][0]
    assert "source_resource_buckets" not in queries[1][0]
    assert 0 < int(str(queries[0][1]["milliseconds"])) <= 5000
    assert owned.browser.timing.failed is missing
    assert len(owned.browser.timing.records) == (0 if missing else 1)
