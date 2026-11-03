"""Diagnostic recording cannot relax the owned probe's acceptance contract."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from owned_phase_trace import PhaseTrace
from test_service_entrypoint_imports import run_refusal_probe


def test_trace_has_fixed_fields_bounded_records_and_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = PhaseTrace(path)
    for _ in range(20):
        trace.mark("launch")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 16
    for row in rows:
        assert set(row) == {"phase", "monotonic_ns", "cpu_ns", "pid", "pgid", "maxrss_kib"}
        assert row.pop("phase") == "launch"
        assert all(isinstance(value, int) and value >= 0 for value in row.values())
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Fixed diagnostic phase required"):
        trace.mark("unrecognized")


def test_trace_unavailable_does_not_change_execution(tmp_path: Path) -> None:
    PhaseTrace(tmp_path / "missing" / "trace.jsonl").mark("launch")


@pytest.mark.parametrize("timeout", [False, True])
def test_refusal_probe_preserves_deadline_result_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    expected = subprocess.CompletedProcess(["owned-probe"], 1, b"", b"service_runtime_failed\n")
    expired = subprocess.TimeoutExpired(["owned-probe"], 5)

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert args == ["owned-probe"]
        assert kwargs["timeout"] == 5
        assert kwargs["capture_output"] is True and kwargs["check"] is False
        assert kwargs["env"]["EM_TEST_PHASE_TRACE"] == str(tmp_path / "refusal-child.jsonl")
        if timeout:
            raise expired
        return expected

    monkeypatch.setattr(subprocess, "run", run)
    if timeout:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            run_refusal_probe(tmp_path, ["owned-probe"])
        assert caught.value is expired
    else:
        assert run_refusal_probe(tmp_path, ["owned-probe"]) is expected
    value = json.loads((tmp_path / "refusal-receipt.json").read_text())
    assert value["classification"] == ("timeout" if timeout else "returned")
    assert value["exit_code"] == (None if timeout else 1)


def test_import_profile_preserves_imports_exceptions_and_hook(tmp_path: Path) -> None:
    import builtins

    from owned_phase_trace import ImportProfile

    original = builtins.__import__
    with ImportProfile(tmp_path / "imports.json") as profile:
        assert profile.imported("json") is json
        with pytest.raises(ModuleNotFoundError):
            profile.imported("nonexistent_private_value")
    assert builtins.__import__ is original
    value = json.loads((tmp_path / "imports.json").read_text())
    assert "nonexistent_private_value" not in json.dumps(value)
    assert value["inclusive_imports"]["other"]["calls"] >= 2
    with pytest.raises(RuntimeError, match="synthetic"):
        with ImportProfile(tmp_path / "failed.json"):
            raise RuntimeError("synthetic")
    assert builtins.__import__ is original


def test_import_profile_bounds_distinct_labels(tmp_path: Path) -> None:
    from owned_phase_trace import ImportProfile

    profile = ImportProfile(tmp_path / "bounded.json")
    profile.original = lambda *args, **kwargs: json
    for number in range(1000):
        profile.imported(f"emailmonitor.synthetic_{number}")
    assert len(profile.rows) <= 257
    assert profile.dropped > 0


def test_timeout_receipt_observes_owned_child_before_unchanged_cleanup(tmp_path: Path) -> None:
    import sys

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_refusal_probe(tmp_path, [sys.executable, "-I", "-c", "import time; time.sleep(10)"])
    assert caught.value.timeout == 5
    value = json.loads((tmp_path / "refusal-receipt.json").read_text())
    observed = value["before_timeout_cleanup"]
    assert observed["observed"] is True and observed["exit_code"] is None
    assert isinstance(observed["pid"], int)
    assert not Path(f"/proc/{observed['pid']}").exists()
