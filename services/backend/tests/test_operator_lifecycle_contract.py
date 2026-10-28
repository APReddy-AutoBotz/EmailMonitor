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
    assert checkpoints.count("lifecycle_unlink_export") == 1
    assert checkpoints.index("lifecycle_export") < checkpoints.index("lifecycle_unlink_export")
    stages = [
        "lifecycle_export",
        "lifecycle_export_preview",
        "lifecycle_export_create",
        "lifecycle_export_wait",
        "lifecycle_export_ready",
        "lifecycle_unlink_export",
    ]
    assert all(checkpoints.count(stage) == 1 for stage in stages)
    assert [checkpoints.index(stage) for stage in stages] == sorted(
        checkpoints.index(stage) for stage in stages
    )
    frame = DiagnosticFrame(kind="failure", stage="lifecycle_unlink_export", error="TimeoutError")
    assert frame.stage == "lifecycle_unlink_export" and frame.error == "TimeoutError"
