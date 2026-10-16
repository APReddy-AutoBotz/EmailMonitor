"""Owned pipe concurrency and failure cleanup; actual worker/UI proof is separate CI."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from operator_provider_worker import PipeOwner
from transport_rpc import OwnedProcess

ROOT = Path(__file__).resolve().parents[3]


def fixture() -> tuple[PipeOwner, list[object]]:
    calls: list[object] = []

    def send(value: object, deadline: float) -> None:
        calls.append((value, deadline))

    def receive(deadline: float) -> dict[str, Any]:
        calls.append(deadline)
        return {"kind": "owned"}

    pipe = PipeOwner(
        cast(OwnedProcess, SimpleNamespace(poisoned=False, send=send, receive=receive))
    )
    pipe.owner = threading.get_ident()
    return pipe, calls


@pytest.mark.parametrize("method", ["send", "receive"])
@pytest.mark.parametrize("invalid", ["unbound", "foreign", "revoked"])
def test_pipe_rejects_unowned_or_revoked_io(method: str, invalid: str) -> None:
    pipe, calls = fixture()
    if invalid == "unbound":
        pipe.owner = None
    elif invalid == "foreign":
        pipe.owner = threading.get_ident() + 1
    else:
        pipe.revoke()
    with pytest.raises(RuntimeError, match="ownership refused"):
        if method == "send":
            pipe.send({"kind": "owned"}, time.monotonic() + 5)
        else:
            pipe.receive(time.monotonic() + 5)
    assert calls == []


@pytest.mark.parametrize("method", ["send", "receive"])
def test_owned_io_preserves_tighter_deadline_and_caps_larger_one(method: str) -> None:
    pipe, calls = fixture()
    now = time.monotonic()
    for deadline in (now + 1, now + 200):
        if method == "send":
            pipe.send({"kind": "owned"}, deadline)
        else:
            assert pipe.receive(deadline) == {"kind": "owned"}
    deadlines = [entry[1] if isinstance(entry, tuple) else entry for entry in calls]
    assert deadlines[0] == now + 1
    assert isinstance(deadlines[1], float) and now + 20 <= deadlines[1] < now + 21


@pytest.mark.parametrize("active", [False, True])
def test_revocation_is_idempotent_and_poisons_only_interrupted_protocol(active: bool) -> None:
    pipe, _ = fixture()
    pipe.active = active
    pipe.revoke()
    pipe.revoke()
    assert pipe.closed.is_set() and pipe.poisoned is active


def test_revocation_waits_for_current_io_but_refuses_late_callback() -> None:
    entered, release, revoked = threading.Event(), threading.Event(), threading.Event()
    calls: list[str] = []
    failures: list[str] = []

    def receive(deadline: float) -> dict[str, Any]:
        entered.set()
        assert release.wait(timeout=3)
        calls.append("receive")
        return {"kind": "owned"}

    pipe = PipeOwner(cast(OwnedProcess, SimpleNamespace(poisoned=False, receive=receive)))
    pipe.active = True

    def worker() -> None:
        pipe.owner = threading.get_ident()
        pipe.receive(time.monotonic() + 3)
        assert revoked.wait(timeout=3)
        try:
            pipe.receive(time.monotonic() + 3)
        except RuntimeError:
            failures.append("late callback refused")

    def closer() -> None:
        pipe.revoke()
        revoked.set()

    thread = threading.Thread(target=worker)
    cleanup = threading.Thread(target=closer)
    thread.start()
    try:
        assert entered.wait(timeout=3)
        cleanup.start()
        assert pipe.closed.wait(timeout=3)
        assert not revoked.is_set()
        release.set()
        assert revoked.wait(timeout=3)
    finally:
        release.set()
        thread.join(timeout=3)
        if cleanup.ident is not None:
            cleanup.join(timeout=3)
    assert not thread.is_alive() and not cleanup.is_alive()
    assert calls == ["receive"] and failures == ["late callback refused"] and pipe.poisoned


def test_worker_and_ui_keep_separate_bounded_controls_and_isolation() -> None:
    helper = (ROOT / "scripts/isolation/operator_provider_worker.py").read_text()
    static = (ROOT / "scripts/isolation/test_operator_ui_acceptance.py").read_text()
    guest = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    workflow = (ROOT / ".github/workflows/transport-isolation.yml").read_text()
    actual = (ROOT / "scripts/isolation/test_operator_provider_acceptance.py").read_text()
    assert "ready.wait(20)" in helper and "thread.join(timeout=150)" in helper
    assert helper.index("pipe.revoke()") < helper.index("thread.join(timeout=150)")
    assert 'pool="solo"' in helper and "app.WorkController(" in helper
    assert "wait_for(complete, seconds=8)" in static
    assert "RPC_DEADLINE = 10.0" in guest and "timeout=75000" in guest
    assert "run_xml_integration.py transport" in workflow
    wrapper = (ROOT / "scripts/packaging/run_xml_integration.py").read_text()
    assert '"transport": ("bash", "scripts/packaging/check_xml_transport.sh")' in wrapper
    assert '(MODES[mode] + ("transport",), MODES[mode] + ("operator",))' in wrapper
    gate = (ROOT / "scripts/packaging/check_xml_transport.sh").read_text()
    assert "test_operator_provider_acceptance.py" in gate
    assert "EM_REQUIRE_REAL_BROKER" in workflow and "EM_REQUIRE_CONTROLLED_NETWORK" in workflow
    assert "consumer_count > 0" in actual and "for q in owned_queues(cfg.queue)" in actual
    assert '"/policies"' in actual and '"/policy-state"' in actual
    assert '"fetch_xml"' in actual
    assert "journey.process(" not in actual and "claim(progress" not in actual


def test_provider_start_uses_unique_workspace_button_with_dashboard_shortcut() -> None:
    import ast

    source = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    module = ast.parse(source)
    branch = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_provider'"
    )
    statement = branch.body[1]
    assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Await)
    action = statement.value.value
    assert isinstance(action, ast.Call) and isinstance(action.func, ast.Name)
    assert action.func.id == "activate"
    # Two actual authored UI controls share this exact accessible name: the
    # Workspace navigation and Dashboard shortcut. Exercise the source selector
    # against that bounded structure, rather than accepting an unscoped .first().
    assert '<nav aria-label="Workspace">' in (ROOT / "apps/web/src/App.tsx").read_text()
    dashboard = (ROOT / "apps/web/src/views.tsx").read_text().split("const defaultOptions")[0]
    assert ">New extraction</button>" in dashboard

    class Locator:
        def __init__(self, nodes: tuple[str, ...]) -> None:
            self.nodes = nodes

        def get_by_role(self, role: str, *, name: str, exact: bool) -> "Locator":
            assert exact is True
            if role == "navigation" and name == "Workspace":
                return Locator(tuple(n for n in self.nodes if n == "navigation"))
            assert role == "button" and name == "New extraction"
            return self

    page = Locator(("navigation", "dashboard"))
    assert len(page.get_by_role("button", name="New extraction", exact=True).nodes) == 2
    target = eval(
        compile(ast.Expression(action.args[1]), "<owned-selector>", "eval"), {"page": page}
    )
    assert isinstance(target, Locator) and target.nodes == ("navigation",)


def test_provider_format_selector_includes_wrapped_option_label_text() -> None:
    import ast
    import re

    source = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_by_label"
        and "Format" in ast.unparse(node)
    ]
    assert len(calls) == 1 and not calls[0].keywords
    pattern = eval(compile(ast.Expression(calls[0].args[0]), "<owned-label>", "eval"), {"re": re})
    # Playwright's label selector includes descendant option text for a wrapped
    # select. Check the actual authored label, not an invented exact short name.
    view = (ROOT / "apps/web/src/views.tsx").read_text()
    label = re.search(r"<label>Format<select.*?</label>", view)
    assert label is not None
    text = "Format" + "".join(re.findall(r"<option[^>]*>([^<]*)</option>", label.group()))
    assert text == "FormatXLSX · literal stringsCSV · conservative formula refusal"
    assert text != "Format" and pattern.search(text)
    assert not pattern.search("Author filter") and not pattern.search("Requested expiry in seconds")
