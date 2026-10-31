"""Closed fixture lifecycle bootstrap and fixed control grammar."""

import json
from unittest.mock import Mock

import pytest
from operator_ui_protocol import validate_journey
from run_operator_ui_acceptance import request_reply


def bootstrap() -> dict[str, object]:
    return {
        "kind": "bootstrap",
        "origin": "https://app.example.test",
        "journey": "controlled_lifecycle",
        "cookies": [],
        "assets": {},
        "initial_organization": "00000000-0000-4000-8000-000000000001",
        "other_organization": "00000000-0000-4000-8000-000000000002",
        "cancel_job": "00000000-0000-4000-8000-000000000003",
        "retry_job": "00000000-0000-4000-8000-000000000004",
    }


def test_lifecycle_bootstrap_requires_exact_owned_identifiers() -> None:
    valid = bootstrap()
    validate_journey(valid)
    for field in valid:
        with pytest.raises(ValueError):
            validate_journey({k: v for k, v in valid.items() if k != field})
    for patch in (
        {"url": "https://untrusted.example"},
        {"cancel_job": "arbitrary"},
        {"retry_job": valid["cancel_job"]},
        {"retry_job": 1},
    ):
        with pytest.raises(ValueError):
            validate_journey({**valid, **patch})


@pytest.mark.parametrize("action", ["hold_lifecycle_reply", "release_lifecycle_reply"])
def test_lifecycle_controls_are_fixed_without_arguments(action: str) -> None:
    control = Mock()
    frame = {"kind": "control", "identifier": 1, "action": action}
    reply = request_reply(Mock(), control, json.dumps(frame).encode(), Mock())
    assert reply["status"] == 200
    control.assert_called_once_with(action)
    with pytest.raises(RuntimeError, match="Owned UI request failed"):
        request_reply(Mock(), control, json.dumps({**frame, "job": "arbitrary"}).encode(), Mock())
    assert control.call_count == 1


def test_added_case_does_not_relax_original_workflow_pin() -> None:
    import hashlib
    from pathlib import Path

    from test_private_affiliation_diagnostic_workflow import (
        PRESERVED_BOUNDARIES,
        lifecycle_operator_baseline,
    )

    original = (
        Path(__file__).resolve().parents[3] / ".github/workflows/operator-ui.yml"
    ).read_bytes()
    expected = PRESERVED_BOUNDARIES[".github/workflows/operator-ui.yml"]
    assert hashlib.sha256(lifecycle_operator_baseline(original)).hexdigest() == expected
    for bad in (
        original.replace(b"timeout-minutes: 20", b"timeout-minutes: 21"),
        original.replace(b"permissions:\n  contents: read", b"permissions: write-all"),
        original.replace(b" -v -s\n", b" -v -s || true\n"),
        original.replace(b"test_operator_lifecycle_acceptance.py", b"optional.py"),
        original.replace(b"test_operator_ui_acceptance.py ", b""),
    ):
        try:
            normalized = lifecycle_operator_baseline(bad)
        except AssertionError:
            continue
        assert hashlib.sha256(normalized).hexdigest() != expected


@pytest.mark.parametrize("mode", ["delayed", "incomplete", "unsequenced"])
def test_cancel_waits_for_resume_render_before_capturing_revision(mode: str) -> None:
    """Execute the authored sequence against a deterministic delayed reply model.

    This proves sequencing, not browser execution or the historical failure's
    exact operation. The genuine hosted journey remains mandatory.
    """
    import ast
    import asyncio
    from pathlib import Path
    from typing import Any

    module = ast.parse(
        (
            Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
        ).read_text()
    )
    journey = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifecycle_journey"
    )
    start = next(
        i
        for i, node in enumerate(journey.body)
        if ast.unparse(node)
        == "await activate(page, page.get_by_role('button', name='Resume', exact=True))"
    )
    end = next(
        i
        for i, node in enumerate(journey.body)
        if ast.unparse(node)
        == (
            "await activate(page, dialog.get_by_role('button', "
            "name='Confirm cancel job', exact=True))"
        )
    )
    sequence = journey.body[start : end + 1]
    readiness = "await expect(page.get_by_role('button', name='Pause', exact=True)).to_be_visible()"
    assert sum(ast.unparse(node) == readiness for node in sequence) == 1
    if mode == "unsequenced":
        sequence = [node for node in sequence if ast.unparse(node) != readiness]
    state = {"revision": 1, "captured": 0, "pending": False, "cancelled": False}
    calls: list[str] = []

    class Locator:
        def __init__(self, name: str) -> None:
            self.name = name

        def get_by_role(self, role: str, *, name: str, exact: bool) -> "Locator":
            assert exact
            return Locator(name)

    class Expect:
        def __init__(self, target: Locator) -> None:
            self.target = target

        async def to_be_visible(self) -> None:
            assert self.target.name == "Pause" and state["pending"]
            calls.append("await resumed render")
            if mode == "incomplete":
                raise TimeoutError("Resume never rendered")
            state["revision"] = 2
            state["pending"] = False

        async def to_contain_text(self, value: str) -> None:
            assert (
                self.target.name == "Cancel job"
                and value == "Retained partial results stay available"
            )

    async def activate(page: Locator, target: Locator) -> None:
        calls.append(target.name)
        if target.name == "Resume":
            state["pending"] = True
        elif target.name == "Cancel job":
            state["captured"] = state["revision"]
        else:
            assert target.name == "Confirm cancel job"
            # Resume can finish after the dialog opens but before confirmation.
            state["revision"] = 2
            if state["captured"] != state["revision"]:
                raise RuntimeError("EXECUTION_REVISION")
            state["cancelled"] = True

    wrapper = ast.parse("async def exercise():\n    pass\n")
    function = wrapper.body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    function.body = sequence
    namespace: dict[str, Any] = {
        "page": Locator("page"),
        "activate": activate,
        "expect": Expect,
        "checkpoint": lambda stage: None,
    }
    exec(compile(ast.fix_missing_locations(wrapper), "<lifecycle-sequence>", "exec"), namespace)
    if mode == "incomplete":
        with pytest.raises(TimeoutError, match="Resume never rendered"):
            asyncio.run(namespace["exercise"]())
        assert "Cancel job" not in calls and not state["cancelled"]
    elif mode == "unsequenced":
        with pytest.raises(RuntimeError, match="EXECUTION_REVISION"):
            asyncio.run(namespace["exercise"]())
        assert not state["cancelled"]
    else:
        asyncio.run(namespace["exercise"]())
        assert calls == ["Resume", "await resumed render", "Cancel job", "Confirm cancel job"]
        assert state["cancelled"]


@pytest.mark.parametrize("mode", ["empty", "pending", "admitted", "never"])
def test_lifecycle_result_requires_bounded_request_drain(mode: str) -> None:
    import ast
    import asyncio
    from pathlib import Path
    from types import SimpleNamespace
    from typing import Any

    module = ast.parse(
        (
            Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
        ).read_text()
    )
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "settle_lifecycle_requests"
    )
    channel = SimpleNamespace(
        pending={1: object()} if mode in {"pending", "never"} else {},
        admitted=0 if mode == "empty" else 1,
    )
    observations: list[tuple[bool, int]] = []

    async def sleep(delay: float) -> None:
        assert delay == 0.05
        observations.append((bool(channel.pending), channel.admitted))
        if mode == "never":
            raise TimeoutError("Owned replies did not settle")
        if len(observations) == 1:
            channel.pending.clear()
        else:
            channel.admitted = 0

    async def wait_for(work: Any, *, timeout: int) -> None:
        assert timeout == 10  # Same bounded drain as the existing hosted journeys.
        await work

    namespace: dict[str, Any] = {
        "Channel": object,
        "asyncio": SimpleNamespace(sleep=sleep, wait_for=wait_for),
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "<lifecycle-drain>", "exec"),
        namespace,
    )
    if mode == "never":
        with pytest.raises(TimeoutError, match="Owned replies did not settle"):
            asyncio.run(namespace["settle_lifecycle_requests"](channel))
        assert channel.pending and channel.admitted == 1
    else:
        asyncio.run(namespace["settle_lifecycle_requests"](channel))
        assert not channel.pending and channel.admitted == 0
        assert len(observations) == (0 if mode == "empty" else 2)

    branch = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_lifecycle'"
    )
    code = ast.unparse(branch)
    assert code.index("await lifecycle_journey") < code.index("Back to recent jobs")
    assert code.index("Recent authorized jobs") < code.index("await settle_lifecycle_requests")
    assert code.index("await settle_lifecycle_requests") < code.index("'kind': 'result'")


def test_unlink_export_stage_is_distinct_from_original_lifecycle_export() -> None:
    import ast
    from pathlib import Path

    from operator_ui_protocol import DiagnosticFrame

    source = Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    module = ast.parse(source.read_text())
    journey = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifecycle_journey"
    )
    checkpoints = [
        ast.literal_eval(node.args[0])
        for node in ast.walk(journey)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "checkpoint"
        and len(node.args) == 1
    ]
    assert checkpoints.count("lifecycle_export") == 1
    assert checkpoints.count("lifecycle_unlink_export_navigation") == 1
    assert checkpoints.index("lifecycle_export") < checkpoints.index(
        "lifecycle_unlink_export_navigation"
    )
    stages = [
        "lifecycle_export",
        "lifecycle_export_preview",
        "lifecycle_export_create",
        "lifecycle_export_wait",
        "lifecycle_export_ready",
        "lifecycle_unlink_export_navigation",
    ]
    assert all(checkpoints.count(stage) == 1 for stage in stages)
    assert [checkpoints.index(stage) for stage in stages] == sorted(
        checkpoints.index(stage) for stage in stages
    )
    for stage in ("lifecycle_unlink_export_navigation", "lifecycle_unlink_export_assertion"):
        frame = DiagnosticFrame(kind="failure", stage=stage, error="TimeoutError")
        assert frame.stage == stage and frame.error == "TimeoutError"


def test_lifecycle_returns_to_jobs_before_leaving_selected_job() -> None:
    """Execute the authored cleanup from the actual post-unlink Exports screen."""
    import ast
    import asyncio
    from pathlib import Path
    from typing import Any

    source = Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    module = ast.parse(source.read_text())
    branch = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_lifecycle'"
    )
    start = next(
        i for i, node in enumerate(branch.body) if "await lifecycle_journey" in ast.unparse(node)
    )
    end = next(
        i
        for i, node in enumerate(branch.body)
        if "await settle_lifecycle_requests" in ast.unparse(node)
    )
    statements = branch.body[start + 1 : end]
    function = ast.AsyncFunctionDef(
        name="cleanup",
        args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=statements,
        decorator_list=[],
        type_params=[],
    )
    state = {"screen": "Exports", "selected": True}

    class SyntheticPage:
        def get_by_role(self, role: str, name: str, exact: bool) -> tuple[str, str]:
            assert exact
            return role, name

    async def activate(page: SyntheticPage, target: tuple[str, str]) -> None:
        assert target[0] == "button"
        if target[1] == "Jobs":
            state["screen"] = "Jobs"
        elif target[1] == "Back to recent jobs":
            assert state["screen"] == "Jobs" and state["selected"]
            state["selected"] = False
        else:
            raise AssertionError("Unexpected synthetic navigation")

    class Visible:
        async def to_be_visible(self) -> None:
            assert state == {"screen": "Jobs", "selected": False}

    def expect(target: tuple[str, str]) -> Visible:
        assert target == ("table", "Recent authorized jobs")
        return Visible()

    stages: list[str] = []
    namespace: dict[str, Any] = {
        "page": SyntheticPage(),
        "activate": activate,
        "expect": expect,
        "checkpoint": stages.append,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
            "<synthetic-cleanup>",
            "exec",
        ),
        namespace,
    )
    asyncio.run(namespace["cleanup"]())
    assert stages == ["lifecycle_cleanup"]


@pytest.mark.parametrize(
    "snapshot",
    [
        "loading_present",
        "alert_present",
        "empty",
        "enabled",
        "disabled",
        "missing",
        "not_exports",
        "unavailable",
    ],
)
def test_unlink_export_failure_preserves_original_and_emits_only_fixed_state(
    monkeypatch: pytest.MonkeyPatch, snapshot: str
) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    import operator_ui_acceptance as guest

    failure = AssertionError("synthetic private assertion must not be emitted")
    page = Mock()
    page.evaluate = AsyncMock(return_value=snapshot)
    assertion = Mock()
    assertion.to_be_disabled = AsyncMock(side_effect=failure)
    monkeypatch.setattr(guest, "expect", Mock(return_value=assertion))
    stages: list[str] = []
    with pytest.raises(AssertionError) as caught:
        asyncio.run(guest.check_lifecycle_unlink_export(page, stages.append))
    assert caught.value is failure
    assert stages == ["lifecycle_unlink_export_assertion", "lifecycle_unlink_export_" + snapshot]
    assert failure.args == ("synthetic private assertion must not be emitted",)
    from guest_outcome import Trace
    from operator_ui_protocol import DiagnosticFrame

    trace = Trace()
    trace.phase = stages[-1]
    assert "phase_" + stages[-1] in trace.label()
    DiagnosticFrame(kind="failure", stage=stages[-1], error="AssertionError")


def test_unlink_export_snapshot_refuses_arbitrary_state_without_masking_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    import operator_ui_acceptance as guest

    failure = AssertionError("synthetic")
    page = Mock()
    page.evaluate = AsyncMock(return_value="untrusted arbitrary value")
    assertion = Mock()
    assertion.to_be_disabled = AsyncMock(side_effect=failure)
    monkeypatch.setattr(guest, "expect", Mock(return_value=assertion))
    stages: list[str] = []
    with pytest.raises(AssertionError) as caught:
        asyncio.run(guest.check_lifecycle_unlink_export(page, stages.append))
    assert caught.value is failure
    assert stages[-1] == "lifecycle_unlink_export_unavailable"


def test_unlink_export_success_preserves_assertion_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    import operator_ui_acceptance as guest

    page = Mock()
    page.evaluate = AsyncMock()
    assertion = Mock()
    assertion.to_be_disabled = AsyncMock()
    monkeypatch.setattr(guest, "expect", Mock(return_value=assertion))
    stages: list[str] = []
    asyncio.run(guest.check_lifecycle_unlink_export(page, stages.append))
    assertion.to_be_disabled.assert_awaited_once_with()
    page.evaluate.assert_not_awaited()
    assert stages == ["lifecycle_unlink_export_assertion"]


@pytest.mark.parametrize("snapshot_failure", ["evaluate", "checkpoint"])
def test_unlink_export_snapshot_failure_does_not_replace_assertion(
    monkeypatch: pytest.MonkeyPatch, snapshot_failure: str
) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    import operator_ui_acceptance as guest

    failure = AssertionError("synthetic assertion")
    page = Mock()
    page.evaluate = AsyncMock(
        side_effect=RuntimeError("synthetic diagnostic failure")
        if snapshot_failure == "evaluate"
        else None,
        return_value="empty",
    )
    assertion = Mock()
    assertion.to_be_disabled = AsyncMock(side_effect=failure)
    monkeypatch.setattr(guest, "expect", Mock(return_value=assertion))

    def checkpoint(stage: str) -> None:
        if stage != "lifecycle_unlink_export_assertion":
            raise RuntimeError("synthetic reporting failure")

    with pytest.raises(AssertionError) as caught:
        asyncio.run(guest.check_lifecycle_unlink_export(page, checkpoint))
    assert caught.value is failure


def test_lifecycle_export_proof_precedes_unlink_and_old_download_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from typing import cast
    from uuid import UUID

    import test_operator_lifecycle_acceptance as harness
    from emailmonitor.organizations.database import AuthorizationDenied
    from emailmonitor.results.service import Results

    export, job, other_job, org = (UUID(int=n) for n in (1, 2, 3, 4))
    state = {"valid": True, "downloads": 0}

    class SyntheticResults:
        def exports(self, selected_org: UUID) -> list[object]:
            assert selected_org == org
            return [SimpleNamespace(id=export, state="ready")]

        def download(self, selected_org: UUID, selected_export: UUID) -> object:
            assert selected_org == org and selected_export == export
            state["downloads"] += 1
            if not state["valid"]:
                raise AuthorizationDenied()
            return SimpleNamespace(body=b"synthetic artifact")

    monkeypatch.setattr(harness, "rows", lambda *_: [["header"], [str(job)]])
    results = SyntheticResults()
    assert harness.verify_lifecycle_export(cast(Results, results), org, job, other_job) == export
    state["valid"] = False
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    assert state["downloads"] == 2


def test_authored_lifecycle_schedules_retained_export_proof_before_unlink() -> None:
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    module = ast.parse(source.read_text())
    journey = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifecycle_journey"
    )
    statements = [ast.unparse(node) for node in journey.body]
    proof = next(
        i for i, statement in enumerate(statements) if "'action': 'verify_retained'" in statement
    )
    unlink = next(i for i, statement in enumerate(statements) if "'Review action'" in statement)
    assert proof < unlink


def test_authored_outcome_next_uses_existing_single_keyboard_trace() -> None:
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    module = ast.parse(source.read_text())
    journey = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "authored_outcome_paging"
    )
    calls = [
        node
        for node in ast.walk(journey)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "traced_activate"
        and "Next article outcome page" in ast.unparse(node)
    ]
    # The loop, first presence activation, and late-organization probe each
    # retain their own passive trace of the same single keyboard activation.
    assert len(calls) == 3
    loop = next(
        node
        for node in ast.walk(journey)
        if isinstance(node, ast.For) and ast.unparse(node.iter) == "range(6)"
    )
    assert sum(node in ast.walk(loop) for node in calls) == 1
    presence = next(
        node.lineno
        for node in ast.walk(journey)
        if isinstance(node, ast.Call)
        and ast.unparse(node) == "checkpoint('outcomes_presence_keyboard')"
    )
    presence_end = next(
        node.lineno
        for node in ast.walk(journey)
        if isinstance(node, ast.Call)
        and "Page 2: 25 article outcomes" in ast.unparse(node)
        and node.lineno > presence
    )
    assert sum(presence < node.lineno < presence_end for node in calls) == 1


def test_job_deletion_failure_metadata_uses_only_fixed_local_phases() -> None:
    import ast
    from pathlib import Path
    from typing import get_args

    from operator_ui_protocol import JobDeletionPhase

    source = Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    module = ast.parse(source.read_text())
    main = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    phases: set[str] = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "deletion_phase"
            for target in node.targets
        ):
            phases.update(
                value.value
                for value in ast.walk(node.value)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
    assert phases == set(get_args(JobDeletionPhase))
    assert '"job_deletion_phase": deletion_phase' in source.read_text()
