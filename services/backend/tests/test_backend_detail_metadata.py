"""Synthetic metadata checks; they do not establish hosted acceptance."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from backend_detail import CASES, KEY, Detail, label, owned_path
from backend_outcome import reported


def record(detail: Detail, node: str, phase: str, outcome: str, duration: float = 1.0) -> None:
    detail.pytest_runtest_logreport(
        SimpleNamespace(nodeid=node, when=phase, outcome=outcome, duration=duration)
    )


def test_detail_path_is_limited_to_the_owned_progress_directory(tmp_path: Path) -> None:
    owned = tmp_path / "em-backend-outcome-synthetic"
    progress, detail = owned / "progress.json", owned / "detail.json"
    assert owned_path(str(progress), str(detail)) == detail
    for wrong in (
        tmp_path / "detail.json",
        owned / "other.json",
        Path("relative/detail.json"),
    ):
        assert owned_path(str(progress), str(wrong)) is None
    assert owned_path(None, str(detail)) is None
    assert owned_path(str(tmp_path / "progress.json"), str(tmp_path / "detail.json")) is None


def test_fixed_cases_and_flushed_module_totals_survive_interruption(tmp_path: Path) -> None:
    path = tmp_path / "detail.json"
    detail = Detail(path)
    unknown = "tests/private-sentinel.py::test_name[secret-parameter]"
    detail.pytest_collection_finish(
        SimpleNamespace(items=[SimpleNamespace(nodeid=n) for n in (*CASES, unknown)])
    )
    detail.pytest_runtest_logstart(CASES[0], ())
    for phase in ("setup", "call", "teardown"):
        record(detail, CASES[0], phase, "passed", 1.5)
    detail.pytest_runtest_logstart(CASES[1], ())
    record(detail, CASES[1], "setup", "passed")
    record(detail, CASES[1], "call", "failed")
    record(detail, CASES[1], "teardown", "passed")
    detail.pytest_runtest_logstart(CASES[2], ())
    record(detail, CASES[2], "setup", "skipped")
    record(detail, CASES[2], "teardown", "passed")
    detail.pytest_runtest_logstart(CASES[3], ())
    value = label(path)
    assert value.startswith("partial-")
    assert "-m1s4n1" in value and "-m2s5n2" in value
    assert value.endswith("-restoreP-brokerFSIN-serviceNNNN")
    assert "private" not in path.read_text() and "secret" not in value


def test_pass_requires_all_three_phases_and_terminal_is_not_acceptance(tmp_path: Path) -> None:
    path = tmp_path / "detail.json"
    detail = Detail(path)
    detail.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=CASES[0])]))
    detail.pytest_runtest_logstart(CASES[0], ())
    record(detail, CASES[0], "setup", "passed")
    record(detail, CASES[0], "teardown", "passed")
    detail.pytest_sessionfinish(None, 1)
    assert label(path).startswith("terminal-")
    assert "-restoreI-" in label(path)


def test_teardown_failure_and_xfail_are_never_reported_as_pass(tmp_path: Path) -> None:
    path = tmp_path / "detail.json"
    detail = Detail(path)
    detail.pytest_collection_finish(
        SimpleNamespace(items=[SimpleNamespace(nodeid=n) for n in CASES[:2]])
    )
    detail.pytest_runtest_logstart(CASES[0], ())
    record(detail, CASES[0], "setup", "passed")
    record(detail, CASES[0], "call", "passed")
    record(detail, CASES[0], "teardown", "failed")
    detail.pytest_runtest_logstart(CASES[1], ())
    record(detail, CASES[1], "setup", "passed")
    detail.pytest_runtest_logreport(
        SimpleNamespace(nodeid=CASES[1], when="call", outcome="passed", duration=1.0, wasxfail="x")
    )
    record(detail, CASES[1], "teardown", "passed")
    assert "-restoreF-brokerSNNN-serviceNNNN" in label(path)


@pytest.mark.parametrize(
    "raw",
    [
        '{"modules":[],"cases":"NNNNNNNNN","terminal":false,"extra":"private"}',
        '{"modules":[],"cases":"NNNNNNNNN","terminal":false,"terminal":true}',
        '{"modules":[[1,true,1]],"cases":"NNNNNNNNN","terminal":false}',
        '{"modules":[],"cases":"private!!","terminal":false}',
        '{"modules":[[2,1,1]],"cases":"NNNNNNNNN","terminal":false}',
    ],
)
def test_untrusted_or_ambiguous_detail_cannot_be_exported(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "detail.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        label(path)


def test_reporting_refuses_arbitrary_data_without_changing_success(tmp_path: Path) -> None:
    output = tmp_path / "output"
    owned: list[Path] = []

    def action(environment: Any) -> None:
        path = Path(environment[KEY])
        owned.append(path.parent)
        path.write_text(json.dumps({"private": "synthetic secret"}))

    reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert output.read_text() == (
        "backend_outcome=normal-exit_0-active_0-completed_0-failed_0-total_0\n"
    )
    assert not owned[0].exists()


def test_unavailable_detail_disables_only_diagnostics(tmp_path: Path) -> None:
    detail = Detail(tmp_path / "missing" / "detail.json")
    detail.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=CASES[0])]))
    assert not detail.enabled
    detail.pytest_runtest_logstart(CASES[0], ())
    record(detail, CASES[0], "setup", "passed")


def test_interrupt_is_not_swallowed_by_detail_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    detail = Detail(tmp_path / "detail.json")

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(Path, "write_text", interrupt)
    with pytest.raises(KeyboardInterrupt):
        detail.save()


def test_real_pytest_timeout_keeps_partial_case_status_and_original_error(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    tests = tmp_path / "services/backend/tests"
    tests.mkdir(parents=True)
    (tests / "test_restore_tenant.py").write_text(
        "def test_actual_restore_replays_current_privacy_before_runtime_and_rebuilds_broker():\n"
        "    pass\n"
    )
    (tests / "test_service_reuse_broker.py").write_text(
        "import os, pytest, time\n"
        "@pytest.mark.parametrize('route',['html','pdf','article_xml','provider'])\n"
        "def test_reused_observation_survives_worker_crash_and_original_redelivery(route):\n"
        "    open(os.environ['OWNED_TEST_READY'], 'w').close()\n"
        "    time.sleep(10)\n"
    )
    child = """
import os
from pathlib import Path
import pytest
from backend_detail import Detail, KEY
raise SystemExit(pytest.main(['-q','-c','/dev/null','--rootdir=.',
    'services/backend/tests/test_restore_tenant.py',
    'services/backend/tests/test_service_reuse_broker.py'],
    plugins=[Detail(Path(os.environ[KEY]))]))
"""
    output = tmp_path / "output"
    owned: list[Path] = []
    caught: list[subprocess.TimeoutExpired] = []

    def action(environment: Any) -> None:
        owned.append(Path(environment[KEY]).parent)
        ready = tmp_path / "ready"
        process = subprocess.Popen(
            [sys.executable, "-c", child],
            cwd=tmp_path,
            env={
                **os.environ,
                **environment,
                "OWNED_TEST_READY": str(ready),
                "PYTHONPATH": str(root / "scripts/packaging"),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            until = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < until:
                assert process.poll() is None
                time.sleep(0.02)
            assert ready.exists()
            process.wait(timeout=0.05)
        except subprocess.TimeoutExpired as error:
            caught.append(error)
            raise
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    with pytest.raises(subprocess.TimeoutExpired) as failure:
        reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert failure.value is caught[0]
    text = output.read_text()
    assert text.startswith("backend_outcome=consumer_deadline-")
    assert "backend_detail=partial-" in text
    assert "-restoreP-brokerINNN-serviceNNNN" in text
    assert not owned[0].exists()


def test_real_pytest_failure_and_skip_keep_exit_and_individual_status(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    tests = tmp_path / "services/backend/tests"
    tests.mkdir(parents=True)
    (tests / "test_restore_tenant.py").write_text(
        "def test_actual_restore_replays_current_privacy_before_runtime_and_rebuilds_broker():\n"
        "    pass\n"
    )
    (tests / "test_service_reuse_broker.py").write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('route',['html','pdf','article_xml','provider'])\n"
        "def test_reused_observation_survives_worker_crash_and_original_redelivery(route):\n"
        "    if route == 'html': assert False, 'private sentinel'\n"
        "    if route == 'pdf': pytest.skip('private sentinel')\n"
    )
    child = """
import os
from pathlib import Path
import pytest
from backend_detail import Detail, KEY as DETAIL
from backend_outcome import Progress, KEY as PROGRESS
raise SystemExit(pytest.main(['-q','-c','/dev/null','--rootdir=.',
    'services/backend/tests/test_restore_tenant.py',
    'services/backend/tests/test_service_reuse_broker.py'],
    plugins=[Progress(Path(os.environ[PROGRESS])), Detail(Path(os.environ[DETAIL]))]))
"""
    output = tmp_path / "output"
    original = RuntimeError("private synthetic consumer error")
    original.outcome_category = "consumer_exit"  # type: ignore[attr-defined]
    original.consumer_code = 1  # type: ignore[attr-defined]

    def action(environment: Any) -> None:
        result = subprocess.run(
            [sys.executable, "-c", child],
            cwd=tmp_path,
            env={
                **os.environ,
                **environment,
                "PYTHONPATH": str(root / "scripts/packaging"),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
        assert result.returncode == 1
        raise original

    with pytest.raises(RuntimeError) as failure:
        reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert failure.value is original
    text = output.read_text()
    assert text.startswith("backend_outcome=test_failure-exit_1-")
    assert "backend_detail=terminal-" in text
    assert "-restoreP-brokerFSPP-serviceNNNN" in text
    assert "private" not in text
