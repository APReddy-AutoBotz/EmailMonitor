"""Execute owned acceptance helpers without importing services or isolation runtimes."""

import ast
import subprocess
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest


def helper(
    name: str,
    namespace: dict[str, Any],
    relative: str = "scripts/isolation/test_transport_acceptance.py",
) -> Any:
    root = Path(__file__).resolve().parents[3]
    source = ast.parse((root / relative).read_text())
    node = next(
        n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            node,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), "owned-acceptance-helper", "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("tenant", [False, True])
def test_actual_acceptance_proxy_explicitly_distinguishes_transport_diagnostics(
    tenant: bool,
) -> None:
    class Tenant:
        resources = object()

    captured: dict[str, Any] = {}

    def gateway(*args: object, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    proxy = helper(
        "proxy",
        {
            "TenantFixtureAuthorization": Tenant,
            "GatewayProxy": gateway,
            "FetchDenied": RuntimeError,
        },
    )
    authorization = Tenant() if tenant else None
    proxy(
        SimpleNamespace(processes={"gateway": object()}),
        uuid4(),
        authorization,
        diagnostic_transport_only=not tenant,
    )
    assert captured["diagnostic_transport_only"] is (not tenant)
    assert captured["resources"] is (Tenant.resources if tenant else None)


def test_held_receipt_observation_propagates_fetch_failure_before_control_polling() -> None:
    pending: Future[bytes] = Future()
    pending.set_exception(RuntimeError("owned-fetch-failed"))

    def snapshot(topology: object) -> object:
        raise AssertionError("Failed fetch must not consume fixture control frames")

    wait = helper(
        "wait_for_held_receipt", {"time": time, "snapshot": snapshot, "cast": cast, "Any": Any}
    )
    with pytest.raises(RuntimeError, match="owned-fetch-failed"):
        wait(object(), pending, time.monotonic() + 10)


def test_held_receipt_observation_keeps_actual_receipt_and_pending_fetch() -> None:
    pending: Future[bytes] = Future()
    receipt = {"received_monotonic": 42.0}
    wait = helper(
        "wait_for_held_receipt",
        {"time": time, "snapshot": lambda topology: {"calls": [receipt]}, "cast": cast, "Any": Any},
    )
    assert wait(object(), pending, time.monotonic() + 10) is receipt
    assert not pending.done()


def test_held_receipt_observation_refuses_early_response_completion() -> None:
    pending: Future[bytes] = Future()
    pending.set_result(b"synthetic")
    wait = helper(
        "wait_for_held_receipt",
        {"time": time, "snapshot": lambda topology: {"calls": []}, "cast": cast, "Any": Any},
    )
    with pytest.raises(AssertionError, match="completed before held receipt"):
        wait(object(), pending, time.monotonic() + 10)


def test_held_receipt_observation_exhaustion_keeps_fixed_frame_bound() -> None:
    clock = [0.0]
    observed = [0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    def snapshot(topology: object) -> dict[str, object]:
        observed[0] += 1
        return {"calls": []}

    wait = helper(
        "wait_for_held_receipt",
        {
            "time": SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep),
            "snapshot": snapshot,
            "cast": cast,
            "Any": Any,
        },
    )
    with pytest.raises(AssertionError, match="request never arrived"):
        wait(object(), Future(), 10.0)
    assert observed[0] <= 50
    assert clock[0] <= 10.0


def test_plain_authorization_wrapper_cannot_implicitly_select_diagnostics() -> None:
    proxy = helper(
        "proxy",
        {"TenantFixtureAuthorization": type("Tenant", (), {}), "FetchDenied": RuntimeError},
    )
    with pytest.raises(RuntimeError, match="source_resource_boundary_required"):
        proxy(object(), uuid4(), lambda url, operation: None)


def test_wrapped_tenant_completion_preserves_real_admission_and_denial() -> None:
    calls: list[str] = []
    ticket = object()

    class Resources:
        def acquire(self, *args: object) -> object:
            calls.append("real-acquire")
            return ticket

        def finish(self, actual: object, status: int | None, retry_after: str) -> None:
            assert actual is ticket
            calls.append("real-finish")
            if status == 200:
                raise RuntimeError("current-policy-refused")

    wrapper_type = helper("CompletionResources", {})
    wrapped = wrapper_type(Resources(), lambda: calls.append("receipt-backed-revoke"))
    assert wrapped.acquire(object(), object(), 10) is ticket
    with pytest.raises(RuntimeError, match="current-policy-refused"):
        wrapped.finish(ticket, 200, "")
    assert calls == ["real-acquire", "receipt-backed-revoke", "real-finish"]
    wrapped.finish(ticket, None, "")
    assert calls[-1] == "real-finish" and calls.count("receipt-backed-revoke") == 1

    class Tenant:
        resources = Resources()

    captured: dict[str, Any] = {}

    def gateway(*args: object, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    proxy = helper(
        "proxy",
        {
            "TenantFixtureAuthorization": Tenant,
            "GatewayProxy": gateway,
            "FetchDenied": RuntimeError,
        },
    )
    proxy(SimpleNamespace(processes={"gateway": object()}), uuid4(), Tenant(), resources=wrapped)
    assert captured["resources"] is wrapped
    assert captured["diagnostic_transport_only"] is False


@pytest.mark.parametrize("url", [None, "https://synthetic.publisher.example/article-a.html"])
def test_owned_keyword_admission_fixture_requests_its_asserted_full_frontier(
    url: str | None,
) -> None:
    from emailmonitor.jobs.models import JobRequest
    from test_job_contracts import request_body

    captured: list[JobRequest] = []
    identifier = uuid4()

    class Ledger:
        def __init__(self, *args: object) -> None:
            pass

        def create(self, organization: object, body: JobRequest, key: object) -> object:
            captured.append(body)
            return identifier

    class Discovery:
        def __init__(self, *args: object) -> None:
            pass

        def plan(self, organization: object, job: object, revision: int) -> None:
            assert job == identifier and revision == 1

    create = helper(
        "new_job",
        {
            "request_body": request_body,
            "Ledger": Ledger,
            "Discovery": Discovery,
            "JobRequest": JobRequest,
            "uuid4": uuid4,
        },
        "services/backend/tests/test_admission_tenant.py",
    )
    assert (
        create(SimpleNamespace(database=object(), token="fixture", settings=object()), uuid4(), url)
        == identifier
    )
    assert len(captured) == 1
    assert captured[0].options.max_articles == (500 if url is None else 1)
    assert captured[0].options.max_search_pages == (2 if url is None else 1)


@pytest.mark.parametrize(
    ("summary", "accepted"),
    [
        ("================ 14 passed in 77.65s ================", True),
        ("14 passed in 77.65s", True),
        ("12 passed in 77.65s", False),
        ("13 passed in 77.65s", False),
        ("114 passed in 77.65s", False),
        ("14 passed_extra", False),
    ],
)
def test_transport_workflow_requires_exact_expanded_case_count(
    summary: str, accepted: bool
) -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/transport-isolation.yml").read_text()
    pattern = "(^|[=[:space:]])14 passed([ ,]|$)"
    assert f"grep -Eq '{pattern}'" in workflow
    result = subprocess.run(
        ["grep", "-Eq", pattern], input=summary, text=True, check=False, timeout=1
    )
    assert (result.returncode == 0) is accepted
    assert "[0-9]+ skipped|[0-9]+ warnings?" in workflow
