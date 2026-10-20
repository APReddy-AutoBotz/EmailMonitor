"""Trusted launcher borrows a verified gateway; it never attests or provisions it."""

import base64
import json
import os
import secrets
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from emailmonitor.config import Settings
from emailmonitor.fetching.provider_proxy import GatewayPipe, ProviderProxy
from emailmonitor.fetching.safety import SafeURL
from emailmonitor.fetching.sciencedirect import ProviderBinding, ProviderBoundary, ProviderRequest
from emailmonitor.parsing.xml_channel import exchange
from emailmonitor.parsing.xml_protocol import XmlExpectation
from emailmonitor.runtime.control_exposure import require_local_control_only
from emailmonitor.runtime.controlled_channel import (
    MAX_CALLBACKS,
    SESSION_COMMANDS,
    FramedSocket,
    require_expectation,
    require_request,
)
from emailmonitor.runtime.controlled_pipes import FramedPipes
from emailmonitor.runtime.pinned_xml import parse_pinned
from emailmonitor.sources.policy import Operation


class _Relay:
    """The token is local bookkeeping only. The SQL ticket never leaves the worker."""

    def __init__(
        self, pipe: FramedSocket | FramedPipes, identifier: str, binding: ProviderBinding
    ) -> None:
        self.pipe, self.identifier, self.binding = pipe, identifier, binding
        self.sequence = 0
        self.ticket: object | None = None

    def callback(self, kind: str, arguments: dict[str, object]) -> None:
        sequence = self.sequence
        self.sequence += 1
        if sequence >= MAX_CALLBACKS:
            raise RuntimeError("Controlled callback limit")
        self.pipe.send(
            {
                "kind": kind,
                "id": self.identifier,
                "sequence": sequence,
                "binding": self.binding.model_dump(mode="json"),
                "arguments": arguments,
            },
            self.binding.deadline,
        )
        reply = self.pipe.receive(self.binding.deadline)
        if (
            reply != {"kind": "callback", "id": self.identifier, "sequence": sequence, "ok": True}
            or type(reply.get("sequence")) is not int
            or reply.get("ok") is not True
        ):
            raise RuntimeError("Controlled callback failed")

    def current(self) -> ProviderBinding:
        self.callback("current", {})
        return self.binding

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        if self.ticket is not None:
            raise RuntimeError("Controlled resource already active")
        self.callback(
            "resource_acquire",
            {"url": url.normalized, "operation": operation.value, "deadline": deadline},
        )
        self.ticket = object()
        return self.ticket

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        if ticket is not self.ticket or ticket is None:
            raise RuntimeError("Controlled resource mismatch")
        self.ticket = None
        self.callback("resource_finish", {"status": status, "retry_after": retry_after})


def serve_request(
    pipe: FramedSocket | FramedPipes,
    gateway: GatewayPipe,
    parser_image_id: str,
    parser_started: Callable[[], None] = lambda: None,
) -> None:
    """One sequential exchange, callable by the owning supervisor thread only."""
    try:
        frame = pipe.receive(time.monotonic() + 20)
        identifier = frame.get("id")
        if (
            type(identifier) is not str
            or len(identifier) != 32
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise ValueError
        if frame.get("kind") == "acquire":
            if set(frame) != {"kind", "id", "request", "binding"}:
                raise ValueError
            request = ProviderRequest.model_validate_json(json.dumps(frame["request"]))
            require_request(request)  # Before even constructing a gateway proxy.
            binding = ProviderBinding.model_validate_json(json.dumps(frame["binding"]))
            if (
                frame["request"] != request.model_dump(mode="json")
                or frame["binding"] != binding.model_dump(mode="json")
                or not 0 < binding.deadline - time.monotonic() <= 20
            ):
                raise ValueError
            relay = _Relay(pipe, identifier, binding)
            boundary = ProviderBoundary(request, binding, relay.current)
            acquired = ProviderProxy(gateway).acquire(boundary, resources=relay)
            if len(acquired.body) > 65536:
                raise ValueError
            pipe.send(
                {
                    "kind": "acquired",
                    "id": identifier,
                    "body": base64.b64encode(acquired.body).decode("ascii"),
                    "digest": acquired.content_digest,
                },
                binding.deadline,
            )
        elif frame.get("kind") == "parse":
            if set(frame) != {"kind", "id", "expected", "body"} or type(frame["body"]) is not str:
                raise ValueError
            expected = XmlExpectation.model_validate_json(json.dumps(frame["expected"]))
            if frame["expected"] != expected.model_dump(mode="json"):
                raise ValueError
            data = base64.b64decode(frame["body"], validate=True)
            require_expectation(expected, data)
            parser_started()
            observed = parse_pinned(
                Settings(environment="test", fixture_mode=True),
                data,
                expected=expected,
                image_id=parser_image_id,
            )
            expected.check_observation(observed)
            pipe.send(
                {
                    "kind": "parsed",
                    "id": identifier,
                    "observation": observed.model_dump(mode="json"),
                },
                time.monotonic() + 20,
            )
        else:
            raise ValueError
    except Exception:
        pipe.poisoned = True
        gateway.poisoned = True
        raise RuntimeError("Controlled capability failed") from None


CONTROL = ("docker", "--host", "unix:///var/run/docker.sock")
ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}
WORKER_COMMAND = ("-m", "emailmonitor.runtime.controlled_entrypoint")
WORKER_PROFILE = (
    "--network=host",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--read-only",
    "--user=65532:65532",
    "--memory=256m",
    "--memory-swap=256m",
    "--cpus=1",
    "--pids-limit=64",
    "--ulimit=nofile=256:256",
    "--ulimit=core=0:0",
    "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
    "--entrypoint=python",
)
OWNER_LABEL = "io.emailmonitor.controlled-worker-owner"


def _image(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in value[7:])
    ):
        raise ValueError("Immutable image required")


def _docker(*args: str, timeout: float = 15) -> bytes:
    output = exchange([*CONTROL, *args], b"", timeout=timeout)
    if len(output) > 65536:
        raise RuntimeError("Controlled container response exceeded limit")
    return output


def _metadata(identifier: str) -> dict[str, Any]:
    value = json.loads(_docker("inspect", identifier))
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise ValueError("Controlled container metadata required")
    return value[0]


def _environment(values: object) -> None:
    if type(values) is not list or any(
        type(value) is not str or "=" not in value for value in values
    ):
        raise ValueError("Controlled image environment required")
    pairs = [value.split("=", 1) for value in values]
    allowed = {
        "PATH",
        "LANG",
        "GPG_KEY",
        "PYTHON_VERSION",
        "PYTHON_SHA256",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
    }
    if len({key for key, _ in pairs}) != len(pairs) or any(key not in allowed for key, _ in pairs):
        raise ValueError("Controlled image environment refused")
    mapped = dict(pairs)
    if (
        mapped.get("PYTHONPATH") != "/opt/emailmonitor/services/backend/src"
        or mapped.get("PYTHONDONTWRITEBYTECODE") != "1"
        or mapped.get("PATH")
        != (
            "/opt/emailmonitor/services/backend/.venv/bin:/usr/local/bin:"
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        )
    ):
        raise ValueError("Installed image environment required")


def verify_worker(metadata: dict[str, Any], image_id: str, name: str, owner: str) -> str:
    identifier = metadata.get("Id")
    config, host = metadata.get("Config"), metadata.get("HostConfig")
    if (
        type(identifier) is not str
        or len(identifier) != 64
        or any(c not in "0123456789abcdef" for c in identifier)
        or type(config) is not dict
        or type(host) is not dict
    ):
        raise ValueError("Owned worker identity required")
    if (
        metadata.get("Image") != image_id
        or metadata.get("Name") != "/" + name
        or config.get("Labels", {}).get(OWNER_LABEL) != owner
    ):
        raise ValueError("Owned worker identity mismatch")
    _environment(config.get("Env"))
    expected = {
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
    }
    mounts = metadata.get("Mounts", [])
    if (
        any(host.get(key) != value for key, value in expected.items())
        or any(
            host.get(key)
            for key in (
                "CapAdd",
                "Binds",
                "Mounts",
                "Devices",
                "DeviceRequests",
                "VolumesFrom",
                "PortBindings",
                "Links",
                "ExtraHosts",
            )
        )
        or config.get("Volumes")
        or config.get("OpenStdin") is not True
        or config.get("Tty") is not False
        or config.get("WorkingDir") != "/opt/emailmonitor"
        or config.get("User") != "65532:65532"
        or config.get("Entrypoint") != ["python"]
        or config.get("Cmd") != list(WORKER_COMMAND)
        or type(mounts) is not list
        or any(
            type(mount) is not dict
            or mount.get("Type") != "tmpfs"
            or mount.get("Destination") != "/tmp"
            or mount.get("Source", "")
            for mount in mounts
        )
        or sorted(host.get("Ulimits", []), key=lambda limit: str(limit.get("Name")))
        != [{"Name": "core", "Hard": 0, "Soft": 0}, {"Name": "nofile", "Hard": 256, "Soft": 256}]
    ):
        raise ValueError("Controlled worker confinement mismatch")
    return identifier


class OwnedWorker:
    """Process-like handle controls the owned container, never merely docker attach."""

    def __init__(self, identifier: str, attached: subprocess.Popen[bytes]) -> None:
        self.identifier, self.attached = identifier, attached
        self.returncode: int | None = None
        self.parser_calls = 0

    def poll(self) -> int | None:
        state = _metadata(self.identifier).get("State", {})
        if state.get("Running") is True:
            return None
        code = state.get("ExitCode")
        if (
            state.get("Running") is not False
            or type(code) is not int
            or state.get("OOMKilled") is not False
        ):
            raise RuntimeError("Controlled worker state invalid")
        self.returncode = code
        return code

    def terminate(self) -> None:
        _docker("stop", "-t", "20", self.identifier, timeout=25)

    def kill(self) -> None:
        _docker("kill", self.identifier)

    def wait(self, timeout: float) -> int:
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("controlled worker", timeout)
            code = self.poll()
            if code is not None:
                self.attached.wait(timeout=max(0.001, deadline - time.monotonic()))
                return code
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def _remove_owned(name: str, image_id: str, owner: str, identifier: str | None) -> None:
    metadata = _metadata(name)
    current = metadata.get("Id")
    if (
        type(current) is not str
        or len(current) != 64
        or any(c not in "0123456789abcdef" for c in current)
        or (identifier is not None and identifier != current)
        or metadata.get("Name") != "/" + name
        or metadata.get("Image") != image_id
        or metadata.get("Config", {}).get("Labels", {}).get(OWNER_LABEL) != owner
    ):
        raise RuntimeError("Controlled worker cleanup identity mismatch")
    _docker("rm", "--force", current)
    if _docker("ps", "--all", "--quiet", "--no-trunc", "--filter", "id=" + current).strip():
        raise RuntimeError("Controlled worker cleanup failed")


@contextmanager
def launched_worker(
    config_path: Path, gateway: GatewayPipe, parser_image_id: str, service_image_id: str
) -> Iterator[OwnedWorker]:
    """Run trusted SQL service code in a verified no-host-control container.

    Host networking is solely the preprovisioned SQL/broker route. The supervisor
    must verify topology and local-only Docker exposure; this is not an untrusted
    worker egress sandbox. Only the parser has a network-none profile.
    """
    from emailmonitor.runtime.entrypoint import load_config

    config = load_config(Path(config_path))
    if config.profile != "controlled-xml-service-reference" or gateway.poisoned:
        raise ValueError("Controlled runtime profile required")
    bootstrap = config.model_dump_json()
    if len(bootstrap.encode()) > 16384:
        raise ValueError("Bounded controlled configuration required")
    _image(parser_image_id)
    _image(service_image_id)
    require_local_control_only()
    image = json.loads(_docker("image", "inspect", service_image_id))
    if type(image) is not list or len(image) != 1 or image[0].get("Id") != service_image_id:
        raise ValueError("Controlled service image mismatch")
    _environment(image[0].get("Config", {}).get("Env"))
    owner = secrets.token_hex(16)
    name = "emailmonitor-service-worker-" + owner
    identifier: str | None = None
    process: OwnedWorker | None = None
    attached: subprocess.Popen[bytes] | None = None
    pipe: FramedPipes | None = None
    thread: threading.Thread | None = None
    stopped = threading.Event()
    failures: list[bool] = []
    attempted = False
    unclaimed: list[int] = []
    try:
        attempted = True
        raw = (
            _docker(
                "create",
                "--pull=never",
                "--interactive",
                "--name=" + name,
                "--label=" + OWNER_LABEL + "=" + owner,
                *WORKER_PROFILE,
                service_image_id,
                *WORKER_COMMAND,
            )
            .decode("ascii")
            .strip()
        )
        if len(raw) != 64 or any(c not in "0123456789abcdef" for c in raw):
            raise ValueError("Controlled worker identity invalid")
        identifier = raw
        if verify_worker(_metadata(identifier), service_image_id, name, owner) != identifier:
            raise ValueError("Controlled worker identity mismatch")
        require_local_control_only()
        attached = subprocess.Popen(
            [*CONTROL, "start", "--attach", "--interactive", identifier],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            env=ENVIRONMENT,
            bufsize=0,
        )
        assert (
            attached.stdin is not None
            and attached.stdout is not None
            and attached.stderr is not None
        )
        for source_stream in (attached.stdout, attached.stdin, attached.stderr):
            unclaimed.append(os.dup(source_stream.fileno()))
        pipe = FramedPipes(*unclaimed)
        unclaimed.clear()
        process = OwnedWorker(identifier, attached)
        pipe.send({"kind": "bootstrap", "config": bootstrap}, time.monotonic() + 20)

        def serve() -> None:
            assert pipe is not None and process is not None
            commands = 0
            try:
                while not stopped.is_set():
                    readers = [pipe.incoming] + ([pipe.errors] if pipe.errors is not None else [])
                    ready = select.select(readers, [], [], 0.2)[0]
                    if stopped.is_set():
                        break
                    if pipe.errors is not None and pipe.errors in ready:
                        pipe._error()
                    if pipe.incoming not in ready:
                        continue
                    if commands >= SESSION_COMMANDS:
                        raise RuntimeError("Controlled session exhausted")
                    commands += 1

                    def parser_started() -> None:
                        assert process is not None
                        if process.parser_calls >= SESSION_COMMANDS:
                            raise RuntimeError("Controlled parser session exhausted")
                        process.parser_calls += 1

                    serve_request(pipe, gateway, parser_image_id, parser_started)
            except Exception:
                if not stopped.is_set():
                    failures.append(True)
                    gateway.poisoned = True
                    pipe.close()
                    try:
                        process.kill()
                    except Exception:
                        failures.append(True)

        thread = threading.Thread(target=serve, name="controlled-xml-owner", daemon=False)
        thread.start()
        yield process
        if failures or process.poll() is not None:
            raise RuntimeError("Controlled worker capability failed")
    finally:
        primary = sys.exception()
        stopped.set()
        cleanup_failed = False
        # Seven parser controls (15s + at-most5s reap), one30s exchange+5s reap,
        # channel20s, worker stop25s, and join margin fit this ownership deadline.
        owner_deadline = time.monotonic() + 240
        try:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    cleanup_failed = True
                    process.kill()
                    process.wait(timeout=20)
        except Exception:
            cleanup_failed = True
        finally:
            for descriptor in unclaimed:
                try:
                    os.close(descriptor)
                except OSError:
                    cleanup_failed = True
            if pipe is not None:
                pipe.close()
            if thread is not None and thread.ident is not None:
                thread.join(timeout=max(0.001, owner_deadline - time.monotonic()))
                if thread.is_alive():
                    cleanup_failed = True
                    gateway.poisoned = True
            if attempted:
                try:
                    _remove_owned(name, service_image_id, owner, identifier)
                except Exception:
                    cleanup_failed = True
            if attached is not None:
                try:
                    if attached.poll() is None:
                        cleanup_failed = True
                        attached.kill()
                    attached.wait(timeout=10)
                except Exception:
                    cleanup_failed = True
                for stream in (attached.stdin, attached.stdout, attached.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            cleanup_failed = True
        if cleanup_failed:
            gateway.poisoned = True
            if primary is None:
                raise RuntimeError("Controlled worker cleanup failed")
            primary.add_note("Controlled worker cleanup failed")
