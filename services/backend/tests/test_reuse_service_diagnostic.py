"""The targeted hosted sample reports fixed categories and preserves failures."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import reuse_service_diagnostic as diagnostic
from backend_detail import CASES


def emit(detail: Any, states: str) -> None:
    nodes = CASES[1:]
    detail.pytest_collection_finish(
        SimpleNamespace(items=[SimpleNamespace(nodeid=n) for n in nodes])
    )
    for node, state in zip(nodes, states, strict=True):
        detail.pytest_runtest_logstart(node, ())
        for phase in ("setup", "call", "teardown"):
            outcome = "failed" if state == "F" and phase == "call" else "passed"
            if state == "S" and phase == "setup":
                outcome = "skipped"
            detail.pytest_runtest_logreport(
                SimpleNamespace(nodeid=node, when=phase, outcome=outcome, duration=0.01)
            )
    detail.pytest_sessionfinish(None, 0)


@pytest.mark.parametrize("code,states", [(0, "PPPPPPPP"), (1, "PFPPPSPP")])
def test_exact_cases_emit_closed_outcomes_without_changing_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, states: str
) -> None:
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    paths: list[Path] = []

    def execute(arguments: list[str], *, plugins: list[Any]) -> int:
        assert tuple(arguments) == diagnostic.ARGUMENTS
        assert len(plugins) == 1
        paths.append(plugins[0].path.parent)
        emit(plugins[0], states)
        return code

    assert diagnostic.run(execute) == code
    value = output.read_text()
    assert len(value.splitlines()) > 8
    assert value.splitlines()[-1].endswith(f"-restoreN-broker{states[:4]}-service{states[4:]}")
    assert "private" not in value
    assert all(not path.exists() for path in paths)


def test_pytest_recognizes_all_diagnostic_hook_signatures(tmp_path: Path) -> None:
    from _pytest.config import PytestPluginManager

    manager = PytestPluginManager()
    manager.register(diagnostic.IncrementalDetail(tmp_path / "detail.json"))
    manager.check_pending()


def test_metadata_failure_does_not_mask_original_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "missing" / "out"))
    original = RuntimeError("synthetic")

    def execute(arguments: list[str], *, plugins: list[Any]) -> int:
        emit(plugins[0], "PPPPPPPP")
        raise original

    with pytest.raises(RuntimeError) as caught:
        diagnostic.run(execute)
    assert caught.value is original


def test_workflow_keeps_original_gates_and_adds_bounded_case_receipt() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/service-runtime.yml").read_text()
    assert "pytest services/backend/tests/test_service_runtime_broker.py -v --tb=short" in workflow
    assert "scripts/packaging/reuse_service_diagnostic.py" in workflow
    assert "steps.reuse-diagnostic.outputs.reuse_diagnostic" in workflow
    assert "continue-on-error" not in workflow
    assert "timeout-minutes: 25" in workflow
    assert len(CASES[1:]) == 8
