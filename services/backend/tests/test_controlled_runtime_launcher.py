"""Authored container control doubles; no Docker, SQL, network, or secret access."""

import copy
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from emailmonitor.runtime import controlled_launcher as launcher
from emailmonitor.runtime import entrypoint
from emailmonitor.runtime.controlled_pipes import FramedPipes
from test_controlled_runtime_channel import IMAGE, Gateway, boundary

IDENTIFIER = "b" * 64
IMAGE_ENV = [
    "PATH=/opt/emailmonitor/services/backend/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONPATH=/opt/emailmonitor/services/backend/src",
    "PYTHONDONTWRITEBYTECODE=1",
]


def metadata() -> dict[str, Any]:
    return {
        "Id": IDENTIFIER,
        "Image": IMAGE,
        "Name": "/emailmonitor-service-worker-" + "c" * 32,
        "Config": {
            "Env": IMAGE_ENV,
            "Labels": {launcher.OWNER_LABEL: "c" * 32},
            "User": "65532:65532",
            "OpenStdin": True,
            "Tty": False,
            "WorkingDir": "/opt/emailmonitor",
            "Entrypoint": ["python"],
            "Cmd": list(launcher.WORKER_COMMAND),
        },
        "HostConfig": {
            "NetworkMode": "host",
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "ReadonlyRootfs": True,
            "Memory": 268435456,
            "MemorySwap": 268435456,
            "NanoCpus": 1000000000,
            "PidsLimit": 64,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
            "PidMode": "",
            "IpcMode": "private",
            "PublishAllPorts": False,
            "Ulimits": [
                {"Name": "core", "Hard": 0, "Soft": 0},
                {"Name": "nofile", "Hard": 256, "Soft": 256},
            ],
        },
        "Mounts": [],
        "State": {"Status": "running", "Running": True, "ExitCode": 0, "OOMKilled": False},
    }


class Attach:
    def __init__(self) -> None:
        incoming, write = os.pipe()
        read, outgoing = os.pipe()
        error_read, error_write = os.pipe()
        self.stdin = os.fdopen(write, "wb", buffering=0)
        self.stdout = os.fdopen(read, "rb", buffering=0)
        self.stderr = os.fdopen(error_read, "rb", buffering=0)
        self.peers = [incoming, outgoing, error_write]
        self.returncode: int | None = None
        self.events: list[str] = []

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.events.append("kill")
        self.returncode = 137

    def wait(self, timeout: float) -> int:
        self.events.append("wait")
        if self.returncode is None:
            self.returncode = 0
        for fd in self.peers:
            os.close(fd)
        self.peers = []
        return self.returncode


def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], list[tuple[str, ...]], dict[str, Any], Attach]:
    monkeypatch.setattr(
        entrypoint,
        "load_config",
        lambda path: SimpleNamespace(
            profile="controlled-xml-service-reference", model_dump_json=lambda: "{}"
        ),
    )
    monkeypatch.setattr(launcher, "require_local_control_only", lambda: None)
    monkeypatch.setattr(secrets, "token_hex", lambda size: "c" * 32)
    state = metadata()
    calls: list[dict[str, Any]] = []
    controls: list[tuple[str, ...]] = []
    attach = Attach()

    def spawn(command: list[str], **kwargs: Any) -> Attach:
        calls.append({"command": command, **kwargs})
        return attach

    def docker(*args: str, timeout: float = 15) -> bytes:
        controls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": IMAGE, "Config": {"Env": IMAGE_ENV}}]).encode()
        if args[0] == "create":
            return IDENTIFIER.encode()
        if args[0] in ("stop", "kill"):
            state["State"]["Running"] = False
            attach.returncode = 0 if args[0] == "stop" else 137
            state["State"]["ExitCode"] = attach.returncode
        return b""

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "_docker", docker)
    monkeypatch.setattr(launcher, "_metadata", lambda identifier, **kwargs: copy.deepcopy(state))
    return calls, controls, state, attach


def test_owned_container_fixed_profile_and_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key in ("AWS_SECRET_ACCESS_KEY", "CELERY_BROKER_URL", "LD_PRELOAD", "DOCKER_HOST"):
        monkeypatch.setenv(key, "must-not-cross")
    calls, controls, _, attach = setup(monkeypatch)
    gateway = Gateway(boundary())
    with launcher.launched_worker(tmp_path / "config.json", gateway, IMAGE, IMAGE) as owned:
        assert owned.identifier == IDENTIFIER
        assert owned.poll() is None and owned.parser_calls == 0
    assert not gateway.poisoned
    assert attach.events == ["wait", "wait"]
    assert calls[0]["env"] == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }
    assert calls[0]["close_fds"] is True and "pass_fds" not in calls[0]
    assert calls[0]["command"] == [
        *launcher.CONTROL,
        "start",
        "--attach",
        "--interactive",
        IDENTIFIER,
    ]
    create = next(command for command in controls if command[0] == "create")
    assert "--network=host" in create and "--read-only" in create and "--user=65532:65532" in create
    assert "--entrypoint=python" in create and not any(
        arg.startswith(("--volume", "--mount", "--device")) for arg in create
    )
    assert ("rm", "--force", IDENTIFIER) in controls
    assert ("stop", "-t", "20", IDENTIFIER) in controls


@pytest.mark.parametrize("code", [0, 1])
def test_unexpected_worker_exit_is_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
) -> None:
    _, _, state, _ = setup(monkeypatch)
    with (
        pytest.raises(RuntimeError, match="capability failed"),
        launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE),
    ):
        state["State"].update(Running=False, ExitCode=code)


@pytest.mark.parametrize("image", ["latest", "sha256:" + "a" * 63, "sha256:" + "G" * 64])
def test_mutable_or_invalid_image_never_starts_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, image: str
) -> None:
    calls, _, _, attach = setup(monkeypatch)
    try:
        with (
            pytest.raises(ValueError, match="Immutable"),
            launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, image),
        ):
            pass
        assert not calls
    finally:
        attach.wait(1)
        for stream in (attach.stdin, attach.stdout, attach.stderr):
            stream.close()


@pytest.mark.parametrize(
    "change",
    [
        "mount",
        "image",
        "owner",
        "entrypoint",
        "privileged",
        "pid",
        "ipc",
        "device",
        "environment",
        "network",
    ],
)
def test_confinement_mutations_refused_before_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str
) -> None:
    calls, _, state, attach = setup(monkeypatch)
    if change == "mount":
        state["Mounts"] = [
            {
                "Type": "bind",
                "Destination": "/var/run/docker.sock",
                "Source": "/var/run/docker.sock",
            }
        ]
    elif change == "image":
        state["Image"] = "sha256:" + "d" * 64
    elif change == "owner":
        state["Config"]["Labels"][launcher.OWNER_LABEL] = "not-owned"
    elif change == "entrypoint":
        state["Config"]["Entrypoint"] = ["sh"]
    elif change == "privileged":
        state["HostConfig"]["Privileged"] = True
    elif change == "pid":
        state["HostConfig"]["PidMode"] = "host"
    elif change == "ipc":
        state["HostConfig"]["IpcMode"] = "host"
    elif change == "device":
        state["HostConfig"]["Devices"] = [{"PathOnHost": "/dev/sda"}]
    elif change == "environment":
        state["Config"]["Env"] = [*IMAGE_ENV, "DOCKER_HOST=tcp://host:2375"]
    elif change == "network":
        state["HostConfig"]["NetworkMode"] = "bridge"
    try:
        with (
            pytest.raises(ValueError),
            launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE),
        ):
            pass
        assert not calls
    finally:
        attach.wait(1)
        for stream in (attach.stdin, attach.stdout, attach.stderr):
            stream.close()


def test_handle_kill_targets_container_and_wait_reaps_attach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, controls, _, attach = setup(monkeypatch)
    owned = launcher.OwnedWorker(IDENTIFIER, attach)  # type: ignore[arg-type]
    owned.kill()
    assert owned.wait(1) == 137 and owned.returncode == 137
    assert ("kill", IDENTIFIER) in controls and attach.events == ["wait"]
    for stream in (attach.stdin, attach.stdout, attach.stderr):
        stream.close()


def test_uncertain_create_still_removes_only_registered_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, controls, _, attach = setup(monkeypatch)
    original = launcher._docker

    def uncertain(*args: str, timeout: float = 15) -> bytes:
        if args[0] == "create":
            raise RuntimeError("fixed uncertain create failure")
        return original(*args, timeout=timeout)

    monkeypatch.setattr(launcher, "_docker", uncertain)
    try:
        with (
            pytest.raises(RuntimeError, match="uncertain create"),
            launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE),
        ):
            pass
        assert ("rm", "--force", IDENTIFIER) in controls
    finally:
        attach.wait(1)
        for stream in (attach.stdin, attach.stdout, attach.stderr):
            stream.close()


def test_forced_reap_failure_preserves_primary_and_closes_all_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, attach = setup(monkeypatch)
    original_wait = attach.wait
    calls = 0

    def wait(timeout: float) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired("controlled worker", timeout)
        return original_wait(timeout)

    monkeypatch.setattr(attach, "wait", wait)
    with (
        pytest.raises(ValueError, match="primary") as error,
        launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE),
    ):
        raise ValueError("primary")
    assert error.value.__notes__ == ["Controlled worker cleanup failed"]
    assert all(stream.closed for stream in (attach.stdin, attach.stdout, attach.stderr))


def test_control_probe_refusal_never_creates_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls, controls, _, attach = setup(monkeypatch)

    def refused() -> None:
        raise RuntimeError("Local control exposure refused")

    monkeypatch.setattr(launcher, "require_local_control_only", refused)
    try:
        with (
            pytest.raises(RuntimeError, match="exposure refused"),
            launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE),
        ):
            pass
        assert not calls and not controls
    finally:
        attach.wait(1)
        for stream in (attach.stdin, attach.stdout, attach.stderr):
            stream.close()


def test_created_transitions_to_running_with_decreasing_inspect_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    budgets: list[float] = []
    statuses = iter(("created", "created", "running"))

    def inspect(identifier: str, *, timeout: float = 15) -> dict[str, Any]:
        budgets.append(timeout)
        status = next(statuses)
        return {
            "Id": identifier,
            "State": {
                "Status": status,
                "Running": status == "running",
                "ExitCode": 0,
                "OOMKilled": False,
            },
        }

    monkeypatch.setattr(launcher, "_metadata", inspect)
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    owned = launcher.OwnedWorker(IDENTIFIER, cast(Any, SimpleNamespace(poll=lambda: None)))
    owned.wait_started(10.2)
    assert len(budgets) == 3 and 0 < budgets[2] < budgets[1] < budgets[0] <= 0.2 + 1e-10
    assert owned.returncode is None


@pytest.mark.parametrize(
    "fault",
    [
        "exited_zero",
        "exited_error",
        "dead",
        "restarting",
        "id",
        "attach",
        "oom",
        "running_mismatch",
        "boolean_exit",
    ],
)
def test_startup_rejects_terminal_or_unverified_state(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    state: dict[str, Any] = {
        "Status": "running",
        "Running": True,
        "ExitCode": 0,
        "OOMKilled": False,
    }
    if fault in ("exited_zero", "exited_error", "dead", "restarting"):
        state.update(Status="exited" if fault.startswith("exited") else fault, Running=False)
        if fault == "exited_error":
            state["ExitCode"] = 1
    elif fault == "oom":
        state["OOMKilled"] = True
    elif fault == "running_mismatch":
        state["Running"] = False
    elif fault == "boolean_exit":
        state["ExitCode"] = False
    monkeypatch.setattr(
        launcher,
        "_metadata",
        lambda identifier, **kwargs: {
            "Id": "d" * 64 if fault == "id" else identifier,
            "State": state,
        },
    )
    owned = launcher.OwnedWorker(
        IDENTIFIER, cast(Any, SimpleNamespace(poll=lambda: 1 if fault == "attach" else None))
    )
    with pytest.raises(RuntimeError, match="startup failed"):
        owned.wait_started(time.monotonic() + 20)


def test_created_startup_exhausts_fixed_deadline_without_yielding_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(
        launcher,
        "_metadata",
        lambda identifier, **kwargs: {
            "Id": identifier,
            "State": {"Status": "created", "Running": False, "ExitCode": 0, "OOMKilled": False},
        },
    )
    owned = launcher.OwnedWorker(IDENTIFIER, cast(Any, SimpleNamespace(poll=lambda: None)))
    with pytest.raises(RuntimeError, match="startup failed"):
        owned.wait_started(10.15)
    assert now[0] == 10.15 and owned.returncode is None


def test_running_report_after_deadline_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    def inspect(identifier: str, *, timeout: float = 15) -> dict[str, Any]:
        assert timeout == 1
        now[0] = 11.0
        return {
            "Id": identifier,
            "State": {"Status": "running", "Running": True, "ExitCode": 0, "OOMKilled": False},
        }

    monkeypatch.setattr(launcher, "_metadata", inspect)
    owned = launcher.OwnedWorker(IDENTIFIER, cast(Any, SimpleNamespace(poll=lambda: None)))
    with pytest.raises(RuntimeError, match="startup failed"):
        owned.wait_started(11.0)


def test_failed_startup_never_yields_and_cleans_owned_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, controls, state, attach = setup(monkeypatch)
    state["State"].update(Status="exited", Running=False, ExitCode=1)
    with (
        pytest.raises(RuntimeError, match="startup failed"),
        launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE),
    ):
        pytest.fail("Unverified worker must not be yielded")
    assert ("rm", "--force", IDENTIFIER) in controls
    assert all(stream.closed for stream in (attach.stdin, attach.stdout, attach.stderr))


def test_bootstrap_and_startup_proof_share_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup(monkeypatch)
    deadlines: list[float] = []
    original_send = FramedPipes.send
    original_wait = launcher.OwnedWorker.wait_started

    def send(self: FramedPipes, value: dict[str, Any], deadline: float) -> None:
        if value.get("kind") == "bootstrap":
            deadlines.append(deadline)
        original_send(self, value, deadline)

    def wait(self: launcher.OwnedWorker, deadline: float) -> None:
        assert deadlines == [deadline]
        original_wait(self, deadline)

    monkeypatch.setattr(FramedPipes, "send", send)
    monkeypatch.setattr(launcher.OwnedWorker, "wait_started", wait)
    with launcher.launched_worker(tmp_path / "config.json", Gateway(boundary()), IMAGE, IMAGE):
        assert len(deadlines) == 1
