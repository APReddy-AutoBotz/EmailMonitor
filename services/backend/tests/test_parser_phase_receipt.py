"""Pure runner doubles only: no Docker, hosted acceptance or isolation claim."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
import run_parser_acceptance as parser


@pytest.mark.parametrize("failure", ["build", "extraction", "memory", "complete"])
def test_fixed_phase_preserves_order_guarded_checks_and_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    output = tmp_path / "output"
    calls: list[str] = []
    sentinel = RuntimeError("Authored exception detail must not enter phase receipt")

    def build(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[0] == "build" and kwargs == {"timeout": 600}
        calls.append("build")
        if failure == "build":
            raise sentinel
        return subprocess.CompletedProcess(args, 0, "", "")

    def run(command: list[str], *, expected_oom: bool = False) -> dict[str, object]:
        phase = "memory" if expected_oom else "extraction"
        calls.append(phase)
        assert command == (
            ["python", "-c", "chunks=[]\nwhile True: chunks.append(bytearray(8 * 1024 * 1024))"]
            if expected_oom
            else ["python", "/app/parser_acceptance.py"]
        )
        if failure == phase:
            raise sentinel
        return {"oom_killed": expected_oom, "exit_code": 137 if expected_oom else 0}

    monkeypatch.setattr(parser, "docker", build)
    monkeypatch.setattr(parser, "run", run)
    # Unit-only injected context; every container operation above is a controlled double.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    if failure == "complete":
        parser.main()
    else:
        with pytest.raises(RuntimeError) as caught:
            parser.main()
        assert caught.value is sentinel
    expected = ["build", "extraction", "memory"]
    assert (
        calls == expected[: expected.index(failure) + 1]
        if failure != "complete"
        else calls == expected
    )
    assert (
        output.read_text()
        == f"phase={failure}\nmemory={'verified' if failure == 'complete' else 'not_verified'}\n"
    )


def test_non_ci_context_refuses_before_commands_or_phase_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(parser, "docker", lambda *a, **k: pytest.fail("No Docker outside CI"))
    with pytest.raises(RuntimeError, match="Reviewed disposable CI"):
        parser.main()
    assert not output.exists()


def test_receipt_io_failure_does_not_replace_original_run_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sentinel = RuntimeError("authored build refusal")

    def refuse(*args: str, **kwargs: Any) -> None:
        raise sentinel

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path))
    monkeypatch.setattr(parser, "docker", refuse)
    with pytest.raises(RuntimeError) as caught:
        parser.main()
    assert caught.value is sentinel


def test_workflow_reports_phase_without_overriding_acceptance_result() -> None:
    workflow = (
        Path(__file__).resolve().parents[3] / ".github/workflows/parser-isolation.yml"
    ).read_text()
    assert "id: parser" in workflow
    assert "steps.parser.outputs.phase || 'unavailable'" in workflow
    assert 'if: always()\n        run: ":"' in workflow
    assert "continue-on-error" not in workflow
    assert "timeout-minutes: 15" in workflow


@pytest.mark.parametrize(
    "category", ["oom_flag_absent_exit137", "other_refusal", "untrusted-value"]
)
def test_memory_refusal_category_is_fixed_and_never_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, category: str
) -> None:
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(parser, "docker", lambda *a, **k: None)
    sentinel = parser.MemoryProofRefused("authored private diagnostic", category)

    def run(command: list[str], *, expected_oom: bool = False) -> dict[str, object]:
        if expected_oom:
            raise sentinel
        return {"oom_killed": False, "exit_code": 0}

    monkeypatch.setattr(parser, "run", run)
    with pytest.raises(parser.MemoryProofRefused) as caught:
        parser.main()
    assert caught.value is sentinel
    expected = category if category == "oom_flag_absent_exit137" else "other_refusal"
    assert output.read_text() == f"phase=memory\nmemory={expected}\n"
