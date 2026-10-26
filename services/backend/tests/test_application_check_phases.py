"""Closed CI phases preserve the complete local aggregate and required join."""

import json
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path

import application_test_partition as partition
import pytest

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = [
    shlex.split(command)
    for command in (
        "uv sync --project services/backend --locked",
        "uv run --project services/backend python -m py_compile scripts/validate_docs.py",
        "uv run --project services/backend python scripts/validate_docs.py",
        "uv run --project services/backend ruff check --config services/backend/pyproject.toml "
        "services/backend/src services/backend/tests services/backend/migrations tests "
        "scripts/check_inventory.py scripts/create_ci_runtime.py "
        "scripts/isolation scripts/packaging",
        "uv run --project services/backend ruff format --check "
        "--config services/backend/pyproject.toml services/backend/src services/backend/tests "
        "services/backend/migrations tests scripts/check_inventory.py scripts/create_ci_runtime.py "
        "scripts/isolation scripts/packaging",
        "uv run --project services/backend mypy --config-file services/backend/pyproject.toml "
        "services/backend/src services/backend/tests services/backend/migrations tests "
        "scripts/create_ci_runtime.py scripts/isolation scripts/packaging",
        "uv run --project services/backend pytest services/backend/tests tests",
        "uv run --project services/backend python scripts/check_inventory.py",
        "pnpm --dir apps/web install --frozen-lockfile --strict-peer-dependencies",
        "pnpm --dir apps/web peers check",
        "pnpm --dir apps/web typecheck",
        "pnpm --dir apps/web lint",
        "pnpm --dir apps/web test",
        "pnpm --dir apps/web build",
    )
]
HOSTED = {
    phase: [
        EXPECTED[0],
        shlex.split(
            "uv run --project services/backend python "
            "scripts/packaging/application_test_partition.py " + profile
        ),
        *([EXPECTED[7]] if profile == "backend" else []),
    ]
    for phase, profile in (("ci-backend", "backend"), ("ci-outcome-sql", "outcome_sql"))
}
DATABASE_KEYS = (
    "EM_TEST_DATABASE_URL",
    "EM_TEST_AUTH_DATABASE_URL",
    "EM_TEST_ADMIN_DATABASE_URL",
)


def run_owned_shell(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Only the synthetic check shell and its descendants belong to this session."""
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # subprocess.run kills only the shell, leaving its active stub alive.
            # No parent/ambient process group is targeted; this PID owns a new session.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=2)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def invoke(
    temporary: Path,
    arguments: tuple[str, ...],
    *,
    tenant: bool = False,
    missing: str = "",
    fail_at: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    directory = temporary / "commands"
    directory.mkdir(exist_ok=True)
    log = temporary / "calls.jsonl"
    log.write_text("")
    stub = f"""#!{sys.executable}
import json, os, pathlib, sys
log = pathlib.Path(os.environ['CHECK_LOG'])
with log.open('a') as output:
    output.write(json.dumps([pathlib.Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')
if len(log.read_text().splitlines()) == int(os.environ['CHECK_FAIL_AT']):
    raise SystemExit(9)
"""
    for tool in ("uv", "pnpm"):
        path = directory / tool
        path.write_text(stub)
        path.chmod(0o700)
    environment = {
        **{key: value for key, value in os.environ.items() if key not in DATABASE_KEYS},
        **{key: "synthetic-disposable-only" for key in DATABASE_KEYS if key != missing},
        "PATH": str(directory) + os.pathsep + os.environ["PATH"],
        "CHECK_LOG": str(log),
        "CHECK_FAIL_AT": str(fail_at),
    }
    script = "scripts/check_tenant_foundation.sh" if tenant else "scripts/check.sh"
    try:
        result = run_owned_shell(
            ["bash", str(ROOT / script), *arguments],
            cwd=temporary,
            env=environment,
            timeout=10,
        )
    except subprocess.TimeoutExpired as error:
        error.add_note(f"Synthetic command records completed: {len(log.read_text().splitlines())}")
        raise
    return result, [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ((), EXPECTED),
        (("all",), EXPECTED),
        (("static",), EXPECTED[:6]),
        (("backend",), [EXPECTED[0], *EXPECTED[6:8]]),
        (("frontend",), EXPECTED[8:]),
        *[((phase,), commands) for phase, commands in HOSTED.items()],
    ],
)
def test_closed_phases_keep_exact_commands_and_default_order(
    tmp_path: Path, arguments: tuple[str, ...], expected: list[list[str]]
) -> None:
    result, calls = invoke(tmp_path, arguments)
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert calls == expected


def test_split_phases_cover_every_default_check_exactly_once(tmp_path: Path) -> None:
    recorded = []
    for phase in ("static", "backend", "frontend"):
        result, calls = invoke(tmp_path, (phase,))
        assert result.returncode == 0
        # Each independent Python job installs the same lock. Only setup repeats.
        recorded.extend(calls[1:] if phase == "backend" else calls)
    assert recorded == EXPECTED


@pytest.mark.parametrize("arguments", [("",), ("unknown",), ("backend", "-k"), ("all", "all")])
@pytest.mark.parametrize("tenant", [False, True])
def test_unknown_or_extra_phase_arguments_refuse_before_commands(
    tmp_path: Path, arguments: tuple[str, ...], tenant: bool
) -> None:
    result, calls = invoke(tmp_path, arguments, tenant=tenant)
    assert result.returncode == 2 and calls == []


@pytest.mark.parametrize("phase", ["static", "frontend"])
def test_tenant_entrypoint_cannot_select_non_backend_phase(tmp_path: Path, phase: str) -> None:
    result, calls = invoke(tmp_path, (phase,), tenant=True)
    assert result.returncode == 2 and calls == []


@pytest.mark.parametrize("missing", DATABASE_KEYS)
@pytest.mark.parametrize("phase", ["backend", *HOSTED])
def test_backend_phase_still_requires_every_disposable_database_url(
    tmp_path: Path, missing: str, phase: str
) -> None:
    result, calls = invoke(tmp_path, (phase,), tenant=True, missing=missing)
    assert result.returncode != 0 and calls == []


@pytest.mark.parametrize("arguments", [(), ("all",), ("backend",), *((key,) for key in HOSTED)])
def test_tenant_entrypoint_keeps_both_migrations_before_closed_phase(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    result, calls = invoke(tmp_path, arguments, tenant=True)
    migration = shlex.split(
        "uv run --project services/backend alembic -c services/backend/alembic.ini upgrade head"
    )
    expected = [EXPECTED[0], *EXPECTED[6:8]] if arguments == ("backend",) else EXPECTED
    if arguments and arguments[0] in HOSTED:
        expected = HOSTED[arguments[0]]
    assert result.returncode == 0 and calls == [migration, migration, *expected]
    source = (ROOT / "scripts/check_tenant_foundation.sh").read_text()
    assert source.count('EM_MIGRATION_DATABASE_URL="$EM_TEST_ADMIN_DATABASE_URL"') == 2


@pytest.mark.parametrize("fail_at", range(1, len(EXPECTED) + 1))
def test_every_default_command_failure_stops_and_fails(tmp_path: Path, fail_at: int) -> None:
    result, calls = invoke(tmp_path, (), fail_at=fail_at)
    assert result.returncode == 9 and calls == EXPECTED[:fail_at]


def workflow_jobs() -> dict[str, str]:
    workflow = (ROOT / ".github/workflows/application.yml").read_text()
    sections = re.split(r"^  (\w+):\n", workflow.split("\njobs:\n", 1)[1], flags=re.MULTILINE)
    return dict(zip(sections[1::2], sections[2::2], strict=True))


def test_workflow_requires_complete_backend_and_static_frontend_jobs() -> None:
    workflow = (ROOT / ".github/workflows/application.yml").read_text()
    jobs = workflow_jobs()
    assert set(jobs) == {"backend", "outcome_sql", "static", "scaffold"}
    assert "continue-on-error" not in workflow
    assert "timeout-minutes: 25" in jobs["backend"]
    for required in (
        'EM_REQUIRE_REAL_BROKER: "true"',
        'EM_TEST_DISPOSABLE_BROKER: "true"',
        'EM_REQUIRE_SYNTHETIC_RESTORE: "true"',
        'EM_REQUIRE_XML_ISOLATION: "true"',
        'EM_REQUIRE_XML_INTEGRATION: "synthetic-test-only"',
        "EM_TEST_BROKER_CONTAINER: ${{ job.services.rabbitmq.id }}",
        "EM_TEST_POSTGRES_CONTAINER: ${{ job.services.postgres.id }}",
        "scripts/packaging/run_xml_integration.py application-backend\n",
        "uv run --project services/backend python scripts/create_ci_runtime.py",
    ):
        assert required in jobs["backend"]
    for key in DATABASE_KEYS:
        assert key + ":" in jobs["backend"]
        assert key not in jobs["static"]
    assert "services:" not in jobs["static"]
    assert "timeout-minutes: 10" in jobs["static"]
    assert jobs["static"].count("run: scripts/check.sh static\n") == 1
    assert jobs["static"].count("run: scripts/check.sh frontend\n") == 1
    assert jobs["outcome_sql"] == jobs["backend"].replace(
        "Execute offline scaffold and real tenant SQL/API checks",
        "Execute the complete retained outcome and article-filter SQL acceptance",
    ).replace("application-backend", "application-outcome-sql")
    assert "partition_receipt: ${{ steps.tests.outputs.partition_receipt }}" in jobs["backend"]
    assert "id: tests" in jobs["backend"]
    for job in ("backend", "outcome_sql", "static"):
        assert "node-version: 24.19.0" in jobs[job]
        assert "pip install uv==0.12.23" in jobs[job]
        assert "npm install --global pnpm@11.25.0" in jobs[job]
        assert "persist-credentials: false" in jobs[job]


@pytest.mark.parametrize("backend", ["success", "failure", "cancelled", "skipped", ""])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "skipped", ""])
@pytest.mark.parametrize("static", ["success", "failure", "cancelled", "skipped", ""])
def test_scaffold_join_accepts_only_three_explicit_successes(
    monkeypatch: pytest.MonkeyPatch, backend: str, outcome: str, static: str
) -> None:
    join = workflow_jobs()["scaffold"]
    assert "if: ${{ always() }}" in join
    assert "needs: [backend, outcome_sql, static]" in join
    assert "timeout-minutes: 1" in join
    assert "BACKEND_RESULT: ${{ needs.backend.result }}" in join
    assert "OUTCOME_SQL_RESULT: ${{ needs.outcome_sql.result }}" in join
    assert "STATIC_RESULT: ${{ needs.static.result }}" in join
    assert "BACKEND_RECEIPT: ${{ needs.backend.outputs.partition_receipt }}" in join
    assert "OUTCOME_SQL_RECEIPT: ${{ needs.outcome_sql.outputs.partition_receipt }}" in join
    assert "run: python3 scripts/packaging/application_test_partition.py join" in join
    assert "persist-credentials: false" in join
    environment = {
        "BACKEND_RESULT": backend,
        "OUTCOME_SQL_RESULT": outcome,
        "STATIC_RESULT": static,
    }
    monkeypatch.setattr(
        partition, "decode_receipt", lambda *args: dict.fromkeys(partition.COMMON, "a")
    )
    monkeypatch.setattr(partition, "source_tree", lambda: "a")
    monkeypatch.setattr(partition, "configuration", lambda: "a")
    if backend == outcome == static == "success":
        partition.join(environment)
    else:
        with pytest.raises(partition.PartitionRefused, match="application_dependency_failed"):
            partition.join(environment)
