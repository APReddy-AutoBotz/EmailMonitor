"""Synthetic-only tests for the fixed one-event runner; no external GETs."""

import hashlib
import http.client
import json
import signal
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import run_private_sample_once as once
import run_xml_integration as integration
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.parsing import private_sample, xml_channel
from test_xml_pipeline import profile


def context() -> tuple[dict[str, str], dict[str, Any]]:
    environment = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": once.REPO,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/pull/42/merge",
        "GITHUB_HEAD_REF": once.HEAD_REF,
        "GITHUB_BASE_REF": once.BASE_REF,
    }
    event = {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "head": {"ref": once.HEAD_REF, "sha": "a" * 40, "repo": {"full_name": once.REPO}},
            "base": {"ref": once.BASE_REF, "sha": once.BASE_SHA, "repo": {"full_name": once.REPO}},
        },
    }
    return environment, event


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_EVENT_NAME", "pull_request_target"),
        ("GITHUB_EVENT_NAME", "push"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_RUN_ATTEMPT", "01"),
        ("GITHUB_REPOSITORY", "foreign/repo"),
        ("GITHUB_REF", "refs/pull/43/merge"),
        ("GITHUB_HEAD_REF", "main"),
        ("GITHUB_BASE_REF", "main"),
        ("HTTPS_PROXY", "https://proxy.example"),
        ("http_proxy", "proxy"),
        ("NO_PROXY", "*"),
        ("DOCKER_HOST", "other"),
        ("SSL_CERT_FILE", "/other"),
        ("SSLKEYLOGFILE", "/private/tls.keys"),
        ("GITHUB_TOKEN", "synthetic-secret"),
        ("ELSEVIER_API_KEY", "synthetic-secret"),
    ],
)
def test_environment_refuses_before_build_or_network(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    environment, event = context()
    environment[key] = value
    called: list[bool] = []
    monkeypatch.setattr(integration, "load_runtime", lambda: called.append(True))
    monkeypatch.setattr(once, "acquire", lambda: called.append(True))
    with pytest.raises(once.Refused):
        once.execute(environment, event)
    assert not called


@pytest.mark.parametrize(
    "mutation",
    [
        "synchronize",
        "reopened",
        "closed",
        "number",
        "fork",
        "base",
        "head",
        "base_sha",
        "head_sha",
        "missing",
    ],
)
def test_event_scope_cannot_be_reused(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    environment, event = context()
    if mutation in {"synchronize", "reopened", "closed"}:
        event["action"] = mutation
    elif mutation == "number":
        event["number"] = 43
    elif mutation == "fork":
        event["pull_request"]["head"]["repo"]["full_name"] = "foreign/repo"
    elif mutation in {"base", "head"}:
        event["pull_request"][mutation]["ref"] = "main"
    elif mutation in {"base_sha", "head_sha"}:
        event["pull_request"][mutation.split("_")[0]]["sha"] = "changed"
    else:
        del event["pull_request"]
    called: list[bool] = []
    monkeypatch.setattr(integration, "load_runtime", lambda: called.append(True))
    with pytest.raises(once.Refused):
        once.execute(environment, event)
    assert not called


def test_event_read_duplicate_and_size_refuse(tmp_path: Path) -> None:
    path = tmp_path / "event.json"
    for data in (b'{"action":"opened","action":"opened"}', b"x" * 1048577, b"[]"):
        path.write_bytes(data)
        with pytest.raises(once.Refused):
            once.read_event(str(path))
    _, event = context()
    path.write_text(json.dumps(event))
    assert once.read_event(str(path)) == event


def transport(
    monkeypatch: pytest.MonkeyPatch, fault: str = ""
) -> tuple[bytes, list[bytes], list[object]]:
    body = b"<synthetic>public authored bytes</synthetic>"
    monkeypatch.setattr(once, "SIZE", len(body))
    monkeypatch.setattr(once, "DIGEST", hashlib.sha256(body).hexdigest())
    sent: list[bytes] = []
    connects: list[object] = []
    address = "127.0.0.1" if fault == "dns_private" else "1.1.1.1"
    records = [(2, 1, 6, "", (address, 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: records)

    class Socket:
        def __enter__(self) -> "Socket":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def settimeout(self, value: float) -> None:
            assert 0 < value <= 10

        def connect(self, target: object) -> None:
            connects.append(target)
            if fault == "connect":
                raise OSError("synthetic private error")

        def getpeername(self) -> tuple[str, int]:
            return ("8.8.8.8" if fault == "peer" else address, 443)

        def sendall(self, data: bytes) -> None:
            sent.append(data)

    class TLS:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, raw: Socket, *, server_hostname: str) -> Socket:
            assert server_hostname == once.HOST
            if fault == "tls":
                raise ssl.SSLError("synthetic private error")
            return raw

    class Response:
        status = 302 if fault == "redirect" else 200

        def __init__(self, secured: Socket) -> None:
            self.data = body if fault != "digest" else b"X" * len(body)
            if fault == "short":
                self.data = self.data[:-1]
            self.headers = {"Content-Length": str(len(body))}
            if fault == "size":
                self.headers["Content-Length"] = str(len(body) + 1)
            if fault == "encoding":
                self.headers["Content-Encoding"] = "gzip"
            if fault == "redirect":
                self.headers["Location"] = "https://other.example/"

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def begin(self) -> None:
            pass

        def getheaders(self) -> list[tuple[str, str]]:
            return list(self.headers.items())

        def getheader(self, name: str) -> str | None:
            return self.headers.get(name)

        def read1(self, bound: int) -> bytes:
            assert 1 <= bound <= 8192
            if fault == "timeout":
                raise TimeoutError("synthetic private error")
            value, self.data = self.data[:bound], self.data[bound:]
            return value

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(ssl, "create_default_context", TLS)
    monkeypatch.setattr(http.client, "HTTPResponse", Response)
    return body, sent, connects


def test_fixed_acquisition_one_pinned_tls_request(monkeypatch: pytest.MonkeyPatch) -> None:
    body, sent, connects = transport(monkeypatch)
    assert once.acquire() == body
    assert connects == [("1.1.1.1", 443)] and len(sent) == 1
    assert sent[0].startswith(f"GET {once.SOURCE_PATH} HTTP/1.1\r\nHost: {once.HOST}\r\n".encode())
    assert b"Authorization" not in sent[0] and b"Cookie" not in sent[0]


@pytest.mark.parametrize(
    "fault",
    [
        "dns_private",
        "peer",
        "tls",
        "connect",
        "redirect",
        "size",
        "encoding",
        "short",
        "digest",
        "timeout",
    ],
)
def test_acquisition_refuses_without_retry(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    _, sent, connects = transport(monkeypatch, fault)
    with pytest.raises((once.Refused, FetchDenied, OSError)):
        once.acquire()
    assert len(sent) <= 1 and len(connects) <= 1
    if fault in {"dns_private", "peer", "tls", "connect"}:
        assert not sent


def lifecycle(monkeypatch: pytest.MonkeyPatch, fault: str = "") -> tuple[list[str], list[Path]]:
    steps: list[str] = []
    paths: list[Path] = []
    image = "sha256:" + "c" * 64
    owner = "d" * 32
    runtime = SimpleNamespace(
        command=lambda *args, **kwargs: b"a" * 40,
        OwnedXmlBuilds=lambda value: SimpleNamespace(owner=owner),
        LABEL="synthetic-owner",
    )
    monkeypatch.setattr(integration, "load_runtime", lambda: runtime)
    monkeypatch.setattr(signal, "alarm", lambda value: 0)

    def prepare(*args: Any) -> tuple[str, dict[str, object]]:
        steps.append("build")
        if fault == "build":
            raise RuntimeError("private@example.org")
        return image, {}

    class Alias:
        def __init__(self, *args: Any) -> None:
            pass

        def install(self) -> None:
            steps.append("alias")

        def verify(self) -> None:
            steps.append("verify")

    def acquire() -> bytes:
        steps.append("acquire")
        if fault == "acquire":
            raise RuntimeError("private@example.org")
        return b"<synthetic/>"

    def evaluate(path: Path, manifest: object) -> dict[str, object]:
        steps.append("evaluate")
        paths.append(path)
        assert path.read_bytes() == b"<synthetic/>"
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert not path.is_relative_to(once.ROOT)
        record = profile()
        config = record["Config"]
        assert isinstance(config, dict)
        config.update(Cmd=list(xml_channel.PRIVATE_COMMAND), Labels={runtime.LABEL: owner})
        record["Image"] = image if fault != "image" else "sha256:" + "f" * 64
        xml_channel.verify_profile(record, private_offline=True)
        if fault == "parse":
            raise RuntimeError("private@example.org")
        return {"status": "observed", "reasons": [], "author_count": 2, "candidate_count": 1}

    def reconcile(*args: Any) -> bool:
        steps.append("cleanup")
        assert all(not path.exists() and not path.parent.exists() for path in paths)
        if fault == "cleanup_error":
            raise RuntimeError("private@example.org")
        return fault != "cleanup"

    monkeypatch.setattr(integration, "prepare_image", prepare)
    monkeypatch.setattr(integration, "OwnedAlias", Alias)
    monkeypatch.setattr(integration, "reconcile", reconcile)
    monkeypatch.setattr(once, "acquire", acquire)
    monkeypatch.setattr(once, "evaluate", evaluate)
    return steps, paths


@pytest.mark.parametrize(
    "fault", ["", "build", "acquire", "parse", "image", "cleanup", "cleanup_error"]
)
def test_lifecycle_redacts_and_cleans_before_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fault: str
) -> None:
    steps, paths = lifecycle(monkeypatch, fault)
    original = xml_channel.verify_profile
    result = once.execute(*context())
    assert steps[-1] == "cleanup" and xml_channel.verify_profile is original
    if fault == "build":
        assert steps == ["build", "cleanup"]
    else:
        assert steps.index("build") < steps.index("acquire")
    assert all(not path.exists() for path in paths)
    assert result["status"] == ("refused" if fault else "observed")
    assert set(result) == {"status", "reasons", "author_count", "candidate_count"}
    assert "private@" not in json.dumps(result)
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_output_rejects_unexpected_fields_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = once.fixed_manifest()
    values = [
        SimpleNamespace(status="observed", author_count=1, candidate_count=1, reasons=[]),
        private_sample.PrivateSampleResult("observed", (), 101, 1),
        private_sample.PrivateSampleResult("observed", ("private@example.org",), 1, 1),  # type: ignore[arg-type]
    ]
    for value in values:
        monkeypatch.setattr(
            private_sample, "evaluate_private_sample", lambda *args, result=value: result
        )
        with pytest.raises(once.Refused):
            once.evaluate(tmp_path / "synthetic", manifest)


def test_fixed_manifest_and_workflow_scope() -> None:
    manifest = once.fixed_manifest()
    assert manifest.sha256 == once.DIGEST and manifest.byte_size == 143976
    assert manifest.requested_identifier.value == "10.1016/j.renene.2013.10.041"
    workflow = (once.ROOT / ".github/workflows/elsevier-one-sample.yml").read_text()
    assert "types: [opened]" in workflow and "github.run_attempt == 1" in workflow
    assert "github.event.number == 42" in workflow and "persist-credentials: false" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" in workflow
    for forbidden in (
        "workflow_dispatch",
        "pull_request_target",
        "upload-artifact",
        "actions/cache",
        "secrets.",
    ):
        assert forbidden not in workflow


def test_outer_deadline_and_temp_cleanup_on_acquisition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    lifecycle(monkeypatch, "acquire")
    alarms: list[int] = []
    directories: list[Path] = []
    original = tempfile.TemporaryDirectory

    def temporary(*args: Any, **kwargs: Any) -> Any:
        created = original(*args, **kwargs)
        directories.append(Path(created.name))
        return created

    monkeypatch.setattr(tempfile, "TemporaryDirectory", temporary)
    monkeypatch.setattr(signal, "alarm", lambda value: alarms.append(value))
    result = once.execute(*context())
    assert result["reasons"] == ["acquisition_refused"]
    assert 40 in alarms and 180 in alarms and alarms[-1] == 0
    assert len(directories) == 1 and not directories[0].exists()


def test_expired_acquisition_deadline_prevents_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    _, sent, connects = transport(monkeypatch)
    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    with pytest.raises(once.Refused):
        once.acquire()
    assert not sent and not connects


def test_entrypoint_missing_event_emits_only_closed_refusal() -> None:
    result = subprocess.run(
        [sys.executable, str(once.ROOT / "scripts/packaging/run_private_sample_once.py")],
        env={},
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 1 and result.stderr == b""
    assert json.loads(result.stdout) == {
        "status": "refused",
        "reasons": ["runner_refused"],
        "author_count": 0,
        "candidate_count": 0,
    }


@pytest.mark.parametrize(
    "fault", ["first_delete", "interrupted_delete", "persistent_delete", "silent_delete"]
)
def test_outer_cleanup_retries_private_deletion_and_verifies_absence(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import tempfile

    steps, paths = lifecycle(monkeypatch)
    original = tempfile.TemporaryDirectory
    directories: list[Any] = []
    attempts: list[bool] = []

    class Temporary:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.owned = original(*args, **kwargs)
            self.name = str(self.owned.name)
            directories.append(self.owned)

        def __enter__(self) -> str:
            return self.name

        def __exit__(self, *args: Any) -> None:
            self.cleanup()

        def cleanup(self) -> None:
            attempts.append(True)
            if fault == "silent_delete":
                return
            if fault == "persistent_delete" or len(attempts) == 1:
                if fault == "interrupted_delete":
                    once.interrupted(15, None)
                raise OSError("private@example.org cannot delete")
            self.owned.cleanup()

    def reconcile(*args: Any) -> bool:
        steps.append("cleanup")
        assert len(attempts) >= 2
        assert paths
        assert paths[0].parent.exists() == (fault in {"persistent_delete", "silent_delete"})
        return True

    monkeypatch.setattr(tempfile, "TemporaryDirectory", Temporary)
    monkeypatch.setattr(integration, "reconcile", reconcile)
    try:
        result = once.execute(*context())
        assert steps[-1] == "cleanup"
        assert result["status"] == "refused"
        if fault in {"persistent_delete", "silent_delete"}:
            assert result["reasons"] == ["cleanup_refused"] and len(attempts) == 3
        else:
            assert len(attempts) == 2 and not paths[0].parent.exists()
        assert "private@" not in json.dumps(result)
    finally:
        for owned in directories:
            owned.cleanup()


def test_private_cleanup_deadline_still_reconciles_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    steps, _ = lifecycle(monkeypatch)

    def expired(temporary: object) -> bool:
        raise integration.CleanupDeadline()

    monkeypatch.setattr(once, "remove_private", expired)
    result = once.execute(*context())
    assert steps[-1] == "cleanup" and result["reasons"] == ["cleanup_refused"]
