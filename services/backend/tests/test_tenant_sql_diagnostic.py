"""Fixed value-free timing never substitutes for real SQL acceptance."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tenant_sql_diagnostic as diagnostic


def test_pytest_accepts_diagnostic_hook_signatures(tmp_path: Path) -> None:
    from _pytest.config import PytestPluginManager

    manager = PytestPluginManager()
    manager.register(diagnostic.SqlDetail(tmp_path / "detail.json"))
    manager.check_pending()


def test_incremental_counts_do_not_confuse_pass_skip_fail_or_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    detail = diagnostic.SqlDetail(tmp_path / "detail.json")
    nodes = [f"tests/test_synthetic.py::test_private_{n}" for n in range(4)]
    detail.pytest_collection_finish(
        SimpleNamespace(items=[SimpleNamespace(nodeid=n) for n in nodes])
    )
    for node, state in zip(nodes, ("pass", "fail", "skip", "incomplete"), strict=True):
        detail.pytest_runtest_logstart(node, ())
        if state == "incomplete":
            continue
        for phase in ("setup", "call", "teardown"):
            outcome = (
                "failed"
                if state == "fail" and phase == "teardown"
                else "skipped"
                if state == "skip" and phase == "setup"
                else "passed"
            )
            detail.pytest_runtest_logreport(
                SimpleNamespace(nodeid=node, when=phase, outcome=outcome, duration=1.0)
            )
    partial = output.read_text().splitlines()[-1]
    assert partial.endswith("-total4-active4-completed3-passed1-failed1-skipped1")
    assert "private" not in partial and "synthetic.py" not in partial
    assert "-m1s9n3" in partial
    detail.pytest_sessionfinish(None, 1)
    assert output.read_text().splitlines()[-1].startswith("tenant_sql_diagnostic=terminal-")


def test_error_propagates_and_cleanup_is_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import test_service_authority_tenant as guard

    monkeypatch.setattr(guard, "require_service_sql_ci", lambda _: None)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    original = RuntimeError("private synthetic exception")
    parents: list[Path] = []

    def execute(arguments: list[str], *, plugins: list[Any]) -> int:
        assert tuple(arguments) == diagnostic.ARGUMENTS
        parents.append(plugins[0].path.parent)
        plugins[0].pytest_collection_finish(SimpleNamespace(items=[]))
        raise original

    with pytest.raises(RuntimeError) as caught:
        diagnostic.run(execute)
    assert caught.value is original
    assert all(not p.exists() for p in parents)
    assert "private" not in (tmp_path / "output").read_text()


def test_guard_refusal_runs_no_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    import test_service_authority_tenant as guard

    def refused(_: dict[str, str]) -> None:
        raise RuntimeError("private reason")

    monkeypatch.setattr(guard, "require_service_sql_ci", refused)
    assert diagnostic.run(lambda *_args, **_kwargs: pytest.fail("unexpected execution")) == 1


def test_workflow_keeps_original_guards_and_fixed_budget() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/service-runtime.yml").read_text()
    assert "scripts/packaging/tenant_sql_diagnostic.py" in workflow
    assert "steps.tenant-sql-diagnostic.outputs.tenant_sql_diagnostic" in workflow
    assert "steps.installed-xml-test.outputs.xml_login_timing" in workflow
    assert "continue-on-error" not in workflow
    assert "timeout-minutes: 25" in workflow
