"""Pure installed XML harness boundaries, not actual Docker/SQL execution evidence."""

import ast
import asyncio
import hashlib
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest
import test_installed_xml_acceptance as harness

ROOT = Path(__file__).resolve().parents[3]


def environment() -> dict[str, str]:
    return {
        "EM_REQUIRE_XML_INTEGRATION": "synthetic-test-only",
        "EM_REQUIRE_CONTROLLED_NETWORK": "true",
        "EM_EXPECTED_XML_IMAGE_ID": "sha256:" + "a" * 64,
        "EM_EXPECTED_XML_IMAGE_OWNER": "b" * 32,
    }


@pytest.mark.parametrize("key", list(environment()))
@pytest.mark.parametrize("value", ["", "true", "synthetic-test-only ", "sha256:latest"])
def test_installed_xml_requires_all_exact_curated_identity_fields(key: str, value: str) -> None:
    env = environment()
    harness.require_xml_context(env)
    env[key] = value
    if env == environment():
        return
    with pytest.raises(RuntimeError, match="Curated installed XML CI identity required"):
        harness.require_xml_context(env)


def test_installed_xml_gate_precedes_sql_and_topology(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def allowed(env: object) -> None:
        order.append("services")

    def refused(env: object) -> None:
        order.append("xml")
        raise RuntimeError("authored XML guard refusal")

    class Request:
        def getfixturevalue(self, name: str) -> None:
            raise AssertionError("No SQL fixture may be resolved before both guards")

    monkeypatch.setattr(harness, "require_installed_ci", allowed)
    monkeypatch.setattr(harness, "require_xml_context", refused)
    with pytest.raises(RuntimeError, match="authored XML guard refusal"):
        harness.installed_xml_scenario.__wrapped__(Request())  # type: ignore[attr-defined]
    assert order == ["services", "xml"]


@pytest.mark.parametrize("change", ["changed", "missing", "extra", "empty"])
def test_installed_supervisor_must_match_complete_verified_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    source_root = tmp_path / "source"
    installed = tmp_path / "installed"
    suffix = "services/backend/src/emailmonitor"
    source, packaged = source_root / suffix, installed / suffix
    source.mkdir(parents=True)
    packaged.mkdir(parents=True)
    (source / "launcher.py").write_text("trusted = True\n")
    (packaged / "launcher.py").write_text("trusted = True\n")
    monkeypatch.setattr(harness, "ROOT", source_root)
    monkeypatch.setattr(
        inspect, "getsourcefile", lambda _: str(source / "runtime/controlled_launcher.py")
    )
    harness.verify_installed_launcher(installed)
    if change == "changed":
        (source / "launcher.py").write_text("trusted = False\n")
    elif change == "missing":
        (source / "launcher.py").unlink()
    elif change == "extra":
        (source / "extra.py").write_text("pass\n")
    else:
        (source / "launcher.py").unlink()
        (packaged / "launcher.py").unlink()
    with pytest.raises(RuntimeError, match="Installed supervisor source"):
        harness.verify_installed_launcher(installed)


@pytest.mark.parametrize("direct", [None, 0, 1, "true", [], {}])
def test_installed_xml_browser_refuses_ambiguous_input_before_ui(
    direct: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import operator_ui_acceptance

    monkeypatch.setitem(sys.modules, "operator_ui_helpers", operator_ui_acceptance)
    browser = importlib.import_module("installed_xml_browser")

    async def login() -> None:
        raise AssertionError("Rejected setup must not invoke login")

    with pytest.raises(ValueError, match="Fixed installed XML input required"):
        asyncio.run(
            browser.xml_journey(
                None,
                None,
                {"direct_article_url": direct},
                lambda _: None,
                login,
                asyncio.Event(),
                lambda phase, format_name: None,
                lambda phase: None,
            )
        )


def test_installed_html_steps_remain_identical_under_separate_branch() -> None:
    source = (ROOT / "scripts/isolation/installed_operator_browser.py").read_text()
    tree = ast.parse(source)
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "controlled_xml"
    )
    xml = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    html = ast.unparse(ast.Module(body=branch.orelse, type_ignores=[]))

    class RemoveExplicitReuse(ast.NodeTransformer):
        count = 0

        def visit_If(self, node: ast.If) -> ast.AST | None:
            if ast.unparse(node.test) == "setup.get('retained_reuse') is True":
                self.count += 1
                reuse = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
                assert not node.orelse
                assert "Request retained observation reuse" in reuse
                assert "Reused observation" in reuse and "needs review" in reuse
                assert "Preview eligible export counts" in reuse
                assert "asyncio.timeout(30)" in reuse
                return None
            return self.generic_visit(node)

    # Keep the frozen original HTML AST intact after excluding the one explicit
    # opt-in reuse journey; it cannot silently alter the legacy HTML steps.
    remover = RemoveExplicitReuse()
    original_html = remover.visit(ast.Module(body=branch.orelse, type_ignores=[]))
    assert remover.count == 1
    assert (
        hashlib.sha256(ast.dump(original_html, include_attributes=False).encode()).hexdigest()
        == "853426f42fc71fb1408bd2262909afe14429f813ebe3e6ecca7ead61a713f30b"
    )
    assert "xml_journey" in xml
    assert "no-contact.html" not in xml
    assert "completed partial" in html and "no-contact.html" in html
    assert "Myocardial Infarction" in html
    assert "asyncio.timeout(55)" in html and "asyncio.timeout(30)" in html
    assert "await login()" in html
    assert "actual_callback" in source and "foreign_tenant_job_denied" in source
    assert '"cookies" in setup' in source and "add_cookies" not in source


def test_installed_reuse_checkpoints_are_fixed_and_scoped_to_opt_in() -> None:
    from operator_ui_protocol import DiagnosticFrame

    tree = ast.parse((ROOT / "scripts/isolation/installed_operator_browser.py").read_text())
    branches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('retained_reuse') is True"
    ]
    assert len(branches) == 1
    calls = sorted(
        (
            node
            for node in ast.walk(branches[0])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "checkpoint"
        ),
        key=lambda node: node.lineno,
    )
    stages = [ast.literal_eval(node.args[0]) for node in calls]
    assert stages == [
        "reuse_plan",
        "reuse_worker",
        "reuse_results",
        "reuse_review",
        "reuse_export",
        "reuse_preview",
    ]
    for stage in stages:
        frame = DiagnosticFrame.model_validate(
            {"kind": "failure", "stage": stage, "error": "TimeoutError"}
        )
        assert frame.stage == stage and frame.reason == "unknown"
    with pytest.raises(ValueError):
        DiagnosticFrame.model_validate(
            {"kind": "failure", "stage": "reuse_private_value", "error": "TimeoutError"}
        )


def test_installed_reuse_checkbox_is_toggled_and_verified_before_cutoff() -> None:
    tree = ast.parse((ROOT / "scripts/isolation/installed_operator_browser.py").read_text())
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('retained_reuse') is True"
    )
    body = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    focused = body.index("await focus(page, reuse_checkbox)")
    toggled = body.index("await page.keyboard.press('Space')", focused)
    verified = body.index("await expect(reuse_checkbox).to_be_checked()", toggled)
    cutoff = body.index("Reuse freshness cutoff UTC", verified)
    assert focused < toggled < verified < cutoff


def test_installed_reuse_result_uses_the_observation_table() -> None:
    tree = ast.parse((ROOT / "scripts/isolation/installed_operator_browser.py").read_text())
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('retained_reuse') is True"
    )
    assignments = [
        node
        for node in ast.walk(branch)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "target_outcomes"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    assert ast.unparse(assignments[0].value) == (
        "page.get_by_role('table', name='Current-authorized article outcomes')"
    )
    body = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    assert "target_outcomes.get_by_text('Reused observation', exact=False)" in body
    assert "to_have_text('needs review')" in body


def test_installed_pdf_evidence_view_matches_actual_authored_association(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import operator_ui_acceptance
    from test_associations import pdf

    monkeypatch.setitem(sys.modules, "operator_ui_helpers", operator_ui_acceptance)
    browser = importlib.import_module("installed_xml_browser")
    actual = pdf("article-a.pdf")
    assert len(actual.associations) == 1
    state = actual.associations[0].state
    assert state == "accepted"
    assert (
        browser.evidence_destination(True)
        == {
            "accepted": "Contacts",
            "needs_review": "Review queue",
        }[state]
    )
    assert browser.evidence_destination(False) == "Review queue"


def test_installed_xml_declares_actual_worker_policy_review_export_and_cleanup() -> None:
    source = (ROOT / "scripts/isolation/test_installed_xml_acceptance.py").read_text()
    browser = (ROOT / "scripts/isolation/installed_xml_browser.py").read_text()
    assert "ProviderJourney(" not in source and "monkeypatch" not in source
    assert 'profile="controlled-xml-service-reference"' in source
    assert "service_image_id=service_image_id" in source
    assert "require_packaged_image" in source and "verify_installed_launcher(installed)" in source
    assert "cleanup_resources(" in source and "value.close()" in source
    assert "Confirm approve synthetic policy" in browser
    assert "does not resolve affiliation uncertainty" in browser
    assert 'enumerate(("xlsx", "csv"))' in browser
    assert "Second@example.org" in browser and "beta@example.org" in browser
    assert "LOCK TABLE emailmonitor.association_batches" in source
    assert "wait_event_type='Lock'" in source and "worker.kill()" in source
    assert 'snapshot(fresh)["calls"] == []' in source
    dockerfile = (ROOT / "scripts/isolation/Dockerfile.installed-operator-ui").read_text()
    assert (
        "COPY scripts/isolation/installed_xml_browser.py ./installed_xml_browser.py" in dockerfile
    )
    workflow = (ROOT / ".github/workflows/service-runtime.yml").read_text()
    assert "pytest scripts/isolation/test_installed_operator_acceptance.py" in workflow
    assert "run_xml_integration.py installed" in workflow


def test_crash_barrier_allows_authority_reads_and_targets_owned_batch_insert() -> None:
    source = inspect.getsource(
        harness.test_installed_controlled_xml_post_observation_crash_recovery
    )
    tree = ast.parse(source)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # ACCESS EXCLUSIVE blocks AccessShare while authority functions are planned,
    # preventing the observation this crash test intends to preserve.
    assert "LOCK TABLE emailmonitor.association_batches IN SHARE MODE" in literals
    assert "ACCESS EXCLUSIVE" not in source
    blocked_query = next(value for value in literals if "FROM pg_stat_activity" in value)
    assert "usename=:name AND wait_event_type='Lock'" in blocked_query
    assert "query LIKE 'INSERT INTO emailmonitor.association_batches%'" in blocked_query
    assert ":barrier_pid=ANY(pg_blocking_pids(pid))" in blocked_query
    assert "SELECT pg_backend_pid()" in literals
    assert 'count("article_observations") != 1' in source
    assert "wait_for(committed_and_blocked, seconds=45)" in source
    assert "worker.wait(timeout=5) == 137" in source
    assert 'snapshot(fresh)["calls"] == []' in source
    assert "recovered.parser_calls == 0" in source


@pytest.mark.parametrize("failure", [None, "build", "help", "probe", "work", "cleanup"])
def test_installed_service_image_owned_lifetime_and_failure_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    from contextlib import nullcontext

    import installed_xml_service_image as image

    from artifacts import canonical, digest

    installed = tmp_path / "installed"
    installed.mkdir()
    payload = b"synthetic installed source\n"
    manifest = canonical(
        {
            "scope": "authored-source-service-reference",
            "production_ready": False,
            "source_tree": "a" * 40,
            "runtime_distributions": {"authored": "1.0"},
            "files": {"module.py": {"sha256": digest(payload), "bytes": len(payload)}},
        }
    )
    (installed / "manifest.json").write_bytes(manifest)
    (installed / "module.py").write_bytes(payload)
    calls: list[str] = []
    original = RuntimeError("owned image authored failure")

    class Owner:
        def __init__(self, owner: str) -> None:
            assert len(owner) == 32

        def build(self, context: Path, ordinal: int) -> str:
            calls.append("build")
            assert ordinal == 1
            assert (context / "module.py").read_bytes() == payload
            assert (context / ".dockerignore").read_text() == "migrations\n"
            assert (context / "manifest.json").read_bytes() == manifest
            assert {p.name for p in context.iterdir()} == {
                "module.py",
                "manifest.json",
                "Dockerfile",
                ".dockerignore",
            }
            if failure == "build":
                raise original
            return "sha256:" + "c" * 64

        def smoke(self, identifier: str, ordinal: int, probe: str | None = None) -> bytes:
            assert identifier == "sha256:" + "c" * 64 and ordinal == 1
            if probe is None:
                calls.append("help")
                return b"invalid" if failure == "help" else b"usage: installed\n"
            calls.append("probe")
            if failure == "probe":
                raise original
            return b"authored-probe"

        def probe_budget(self) -> Any:
            return nullcontext()

        def close(self) -> None:
            calls.append("close")
            if failure == "cleanup":
                raise original

    def validate(output: bytes, files: dict[str, bytes], runtime: dict[str, str]) -> None:
        calls.append("validate")
        assert output == b"authored-probe" and files["module.py"] == payload
        assert runtime == {"authored": "1.0"}

    monkeypatch.setattr(image, "OwnedServiceBuilds", Owner)
    monkeypatch.setattr(image, "validate_smoke", validate)
    try:
        with image.installed_service_image(installed, tmp_path / "context") as identifier:
            calls.append("work")
            assert identifier == "sha256:" + "c" * 64
            assert "close" not in calls and calls[-2] == "validate"
            if failure == "work":
                raise original
    except RuntimeError as error:
        assert failure is not None
        if failure != "help":
            assert error is original
    else:
        assert failure is None
    assert calls[-1] == "close" and calls.count("close") == 1
    if failure in {"build", "help", "probe"}:
        assert "work" not in calls


def test_installed_revocation_keeps_existing_held_response_boundaries() -> None:
    source = (ROOT / "scripts/isolation/test_installed_xml_acceptance.py").read_text()
    tree = ast.parse(source)
    test = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_installed_controlled_xml_delegation_revoked_before_response_release"
    )
    body = ast.unparse(test)
    assert "configure(network, 'slow')" in body
    assert "range(50)" in body and "time.monotonic() + 10" in body
    assert "time.monotonic() - calls[0]['received_monotonic'] < 15" in body
    assert "UPDATE emailmonitor.service_delegations" in body
    assert "principal_id=:principal" in body and "id=:grant" in body
    assert "organization_id IN (:org,:other)" in body
    assert "worker.parser_calls == 0" in body
    assert "article_observations" in body and "association_batches" in body
    assert "execution_effects" in body and "len(calls) == 1" in body
    assert "resource_state.state == 'finished'" in body
    assert "resource_state.state == 'active' and resource_state.bounded is True" in body
    assert "monkeypatch" not in body and "ProviderJourney(" not in body


@pytest.mark.parametrize("failure", [None, "send", "reply", "poisoned"])
def test_actual_revocation_release_is_once_only_even_after_ambiguous_failure(
    failure: str | None,
) -> None:
    from types import SimpleNamespace

    source = (ROOT / "scripts/isolation/test_installed_xml_acceptance.py").read_text()
    tree = ast.parse(source)
    test = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_installed_controlled_xml_delegation_revoked_before_response_release"
    )
    release = next(
        node
        for node in ast.walk(test)
        if isinstance(node, ast.FunctionDef) and node.name == "release"
    )
    wrapper = ast.parse(
        "def build():\n    release_attempted = False\n    release_ack = False\n"
        "    return release, lambda: (release_attempted, release_ack)\n"
    ).body[0]
    assert isinstance(wrapper, ast.FunctionDef)
    wrapper.body.insert(2, release)
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    calls: list[str] = []

    class Fixture:
        poisoned = failure == "poisoned"

        def send(self, value: object, deadline: float) -> None:
            calls.append("send")
            assert value == {"kind": "release"} and deadline == 8.0
            if failure == "send":
                raise RuntimeError("authored uncertain send")

        def receive(self, deadline: float) -> dict[str, str]:
            calls.append("receive")
            assert deadline == 8.0
            return {"kind": "wrong" if failure == "reply" else "released"}

    fixture = Fixture()
    namespace: dict[str, Any] = {
        "network": SimpleNamespace(processes={"fixture-a": fixture}),
        "time": SimpleNamespace(monotonic=lambda: 3.0),
    }
    exec(compile(module, "actual-installed-revocation-release", "exec"), namespace)
    action, state = namespace["build"]()
    if failure is None:
        action()
        assert calls == ["send", "receive"] and not fixture.poisoned
    else:
        with pytest.raises((RuntimeError, AssertionError)):
            action()
        assert fixture.poisoned
    assert state() == (True, failure is None)
    previous = list(calls)
    action()
    assert calls == previous
    assert state() == (True, failure is None)


@pytest.mark.parametrize(
    "field",
    [
        "phase",
        "origin",
        "failure",
        "callback_kind",
        "callback_sent",
        "callback_received",
        "callback_validated",
        "last_completed_kind",
        "worker_elapsed_bucket",
        "supervisor_roundtrip_bucket",
        "initial_acquire_remaining_bucket",
    ],
)
@pytest.mark.parametrize("hostile", ["SECRET https://private.invalid", True, -1, 129, object()])
def test_worker_failure_note_refuses_untrusted_fields(field: str, hostile: object) -> None:
    from dataclasses import replace
    from types import SimpleNamespace

    from emailmonitor.runtime.controlled_diagnostics import (
        CallbackKind,
        DiagnosticSnapshot,
        Failure,
        Origin,
        Phase,
    )

    valid = DiagnosticSnapshot(
        phase=next(iter(Phase)),
        origin=next(iter(Origin)),
        failure=next(iter(Failure)),
        callback_kind=next(iter(CallbackKind)),
        callback_sent=0,
        callback_received=0,
        callback_validated=0,
    )
    damaged = replace(valid, **{field: hostile})  # type: ignore[arg-type]
    assert (
        harness.worker_failure_note(SimpleNamespace(diagnostic_snapshot=damaged))
        == "Installed XML worker diagnostic unavailable"
    )


def test_worker_failure_note_property_failure_is_not_rendered() -> None:
    class Hostile:
        @property
        def diagnostic_snapshot(self) -> object:
            raise RuntimeError("SECRET private configuration")

    assert harness.worker_failure_note(Hostile()) == "Installed XML worker diagnostic unavailable"
    assert (
        harness.worker_failure_note({"diagnostic_snapshot": "SECRET"})
        == "Installed XML worker diagnostic unavailable"
    )


@pytest.mark.parametrize("body_fails", [True, False])
def test_diagnosed_worker_preserves_original_failure_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, body_fails: bool
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    from emailmonitor.runtime.controlled_diagnostics import (
        CallbackKind,
        DiagnosticSnapshot,
        Failure,
        Origin,
        Phase,
    )

    worker = SimpleNamespace(
        diagnostic_snapshot=DiagnosticSnapshot(
            phase=next(iter(Phase)),
            origin=next(iter(Origin)),
            failure=next(iter(Failure)),
            callback_kind=next(iter(CallbackKind)),
            callback_sent=128,
            callback_received=3,
            callback_validated=2,
        )
    )
    original = AssertionError("original failure")
    events: list[str] = []

    @contextmanager
    def launch(*args: object, **kwargs: object) -> Any:
        assert args == ("config", "gateway", "parser")
        assert kwargs == {"service_image_id": "image"}
        try:
            yield worker
        finally:
            if body_fails:
                assert len(original.__notes__) == 1
            events.append("cleanup")
        if not body_fails:
            raise original

    monkeypatch.setattr(harness, "launched_worker", launch)
    with pytest.raises(AssertionError) as caught:
        with harness.diagnosed_worker(
            "config", "gateway", "parser", service_image_id="image"
        ) as running:
            assert running is worker
            if body_fails:
                raise original
    assert caught.value is original
    assert events == ["cleanup"]
    assert len(original.__notes__) == 1
    note = original.__notes__[0]
    assert note.startswith("Installed XML worker diagnostic {")
    assert len(note) < 640
    assert '"callback_sent": 128' in note


def test_all_installed_xml_worker_cases_have_failure_diagnostics() -> None:
    source = inspect.getsource(harness)
    assert source.count("with diagnosed_worker(") == 4
    assert source.count("with launched_worker(") == 1


def test_diagnosed_worker_success_does_not_read_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    class Worker:
        @property
        def diagnostic_snapshot(self) -> object:
            raise AssertionError("Success must not inspect diagnostics")

    worker = Worker()

    @contextmanager
    def launch() -> Any:
        yield worker

    monkeypatch.setattr(harness, "launched_worker", launch)
    with harness.diagnosed_worker() as running:
        assert running is worker


@pytest.mark.parametrize("direct", [False, True])
def test_expected_persisted_input_matches_existing_normalization(direct: bool) -> None:
    from emailmonitor.jobs.models import KeywordInput, URLInput

    expected = harness.expected_job_input(direct)
    model = URLInput if direct else KeywordInput
    supplied = dict(expected)
    supplied.pop("query_change_confirmed", None)
    assert model.model_validate(supplied).model_dump(exclude_none=True) == expected
    if not direct:
        assert expected["query_change_confirmed"] is False
    assert {**expected, "unexpected": True} != expected


def test_expected_worker_failure_preserves_diagnostic_notes_and_original_arguments() -> None:
    original = RuntimeError("Controlled worker capability failed")
    original.add_note("Installed XML worker diagnostic TIMEOUT")
    with pytest.raises(RuntimeError) as caught:
        raise original
    harness.assert_expected_worker_failure(caught.value)
    assert caught.value is original
    assert original.__notes__ == ["Installed XML worker diagnostic TIMEOUT"]
    assert original.args == ("Controlled worker capability failed",)


@pytest.mark.parametrize(
    "arguments", [(), ("different failure",), ("Controlled worker capability failed", "extra")]
)
def test_expected_worker_failure_rejects_other_arguments(arguments: tuple[str, ...]) -> None:
    error = RuntimeError(*arguments)
    error.add_note("Controlled worker capability failed")
    with pytest.raises(AssertionError):
        harness.assert_expected_worker_failure(error)


@pytest.mark.parametrize(
    ("function", "milestones"),
    [
        (
            harness.test_installed_controlled_xml_post_observation_crash_recovery,
            ("crash_kill_completed",),
        ),
        (
            harness.test_installed_controlled_xml_delegation_revoked_before_response_release,
            (
                "held_request_validated",
                "revocation_committed",
                "release_ack",
                "test_body_completed",
            ),
        ),
    ],
)
def test_expected_failure_requires_completed_milestones_after_raises(
    function: Any, milestones: tuple[str, ...]
) -> None:
    tree = ast.parse(inspect.getsource(function))
    raises = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and any(
            ast.unparse(item.context_expr) == "pytest.raises(RuntimeError)" for item in node.items
        )
    )
    assert raises.end_lineno is not None
    for name in milestones:
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        ]
        assert {ast.unparse(node.value) for node in assignments} == {"False", "True"}
        final_check = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert) and ast.unparse(node.test) == name
        )
        assert final_check.lineno > raises.end_lineno
        # An early expected launcher failure must still fail the milestone check.
        statement = ast.Module(body=[final_check], type_ignores=[])
        with pytest.raises(AssertionError):
            exec(compile(statement, "<authored milestone>", "exec"), {name: False})
    source = inspect.getsource(function)
    if "revocation_committed" in milestones:
        assert source.index("revocation_committed = True") > source.index("assert revoked ==")
        assert source.index("release_ack = True") > source.index("fixture.receive(deadline) ==")
        assert "nonlocal release_attempted, release_ack" in source


def test_export_failure_receipt_keeps_publisher_failure_when_sql_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from uuid import uuid4

    stopped = threading.Event()
    stopped.set()

    def unavailable(*args: object) -> None:
        raise RuntimeError("sensitive database message must not escape")

    monkeypatch.setattr(harness, "owned_export_states", unavailable)
    note = harness.export_failure_note("private-url", uuid4(), uuid4(), None, stopped, True, True)
    assert '"publisher_failed": true' in note
    assert '"publisher_stop_requested": true' in note
    assert '"exports": "unavailable"' in note
    assert "sensitive" not in note and "private-url" not in note


def test_export_failure_receipt_records_only_fixed_owned_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from uuid import uuid4

    import guest_outcome

    guest_outcome.reset_case_trace()
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setattr(
        harness,
        "owned_export_states",
        lambda *_: [
            {
                "format": "csv",
                "state": "queued",
                "attempts": 0,
                "lease_present": False,
                "lease_active": False,
                "pending": True,
                "confirmed": False,
                "delivered": False,
            }
        ],
    )
    note = harness.export_failure_note(
        "private-url", uuid4(), uuid4(), None, threading.Event(), False, True
    )
    assert "private-url" not in note
    assert guest_outcome.case_export_snapshot() == "p00001.csv_queued.0.00100"


@pytest.mark.parametrize(
    "change",
    [
        {"format": "private-content"},
        {"state": "unknown"},
        {"attempts": True},
        {"attempts": 4},
        {"pending": "false"},
        {"export_id": "private-id"},
    ],
)
def test_export_receipt_rejects_unbounded_or_coerced_data(change: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        harness.ExportStateReceipt.model_validate(
            {
                "format": "xlsx",
                "state": "queued",
                "attempts": 0,
                "lease_present": False,
                "lease_active": False,
                "pending": True,
                "confirmed": False,
                "delivered": False,
                **change,
            }
        )


def test_export_state_query_is_owned_bounded_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    from uuid import uuid4

    organization, owner = uuid4(), uuid4()
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = []
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(harness, "create_engine", factory)
    assert harness.owned_export_states("existing-test-admin", organization, owner) == []
    assert factory.call_args.kwargs["connect_args"] == {"timeout": 0.5}
    assert factory.call_args.kwargs["hide_parameters"] is True
    statements = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    assert statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout='500ms'",
        "SET LOCAL lock_timeout='100ms'",
    ]
    query, parameters = connection.execute.call_args.args
    assert "e.organization_id=:org AND e.requested_by=:owner" in str(query)
    assert "o.organization_id=e.organization_id AND o.export_id=e.id" in str(query)
    assert "o.generation=e.generation" in str(query)
    assert str(query).endswith("LIMIT 3")
    assert parameters == {"org": organization, "owner": owner}
    engine.dispose.assert_called_once_with()
