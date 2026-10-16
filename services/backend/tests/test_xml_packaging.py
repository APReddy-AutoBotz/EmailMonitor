"""Pure XML artifact boundary checks; actual images remain a required separate CI gate."""

import importlib.metadata
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import xml_artifacts

from artifacts import BASE, NOTICES, PackagingRefused, archive, digest
from run_acceptance import LABEL

ROOT = Path(__file__).resolve().parents[3]
TREE = "a" * 40
RUNTIME = {"pydantic": "2.14.0"}


@pytest.fixture
def xml_inputs(tmp_path: Path) -> Path:
    paths = [
        *("services/backend/src/emailmonitor/" + name for name in xml_artifacts.XML_FILES),
        "services/backend/pyproject.toml",
        "services/backend/uv.lock",
        *NOTICES,
    ]
    for name in paths:
        source, target = ROOT / name, tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def test_explicit_worker_entrypoint_import_closure() -> None:
    files = set(xml_artifacts.XML_FILES)
    assert len(files) == 33
    assert "parsing/xml_worker.py" in files
    assert "fetching/fixture.py" in files  # Shared helper code is deliberately disclosed.
    assert "api.py" not in files
    assert "identity/foundation.py" not in files
    for name in files:
        path = ROOT / "services/backend/src/emailmonitor" / name
        assert path.is_file() and path.suffix == ".py"
        parent = Path(name).parent
        while str(parent) != ".":
            assert (parent / "__init__.py").as_posix() in files
            parent = parent.parent
    code = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import emailmonitor.parsing.xml_worker
import emailmonitor
root = pathlib.Path(emailmonitor.__file__).parent
print(json.dumps(sorted(str(pathlib.Path(module.__file__).relative_to(root))
    for name, module in sys.modules.items()
    if name == 'emailmonitor' or name.startswith('emailmonitor.'))))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "services/backend/src")],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert not result.stderr
    assert set(json.loads(result.stdout)) == files


def test_two_xml_archives_are_deterministic_and_roundtrip(xml_inputs: Path) -> None:
    first = xml_artifacts.collect(xml_inputs, TREE, RUNTIME)
    second = xml_artifacts.collect(xml_inputs, TREE, dict(reversed(list(RUNTIME.items()))))
    assert first == second
    blob = archive(first)
    assert blob == archive(dict(reversed(list(second.items()))))
    assert xml_artifacts.verify_archive(blob, TREE, RUNTIME) == first
    manifest = json.loads(first["manifest.json"])
    assert manifest["source_tree"] == TREE
    assert manifest["production_ready"] is False
    assert manifest["working_extraction_service"] is False
    assert manifest["runtime_distributions"] == RUNTIME
    assert manifest["base_image"] == BASE
    with tarfile.open(fileobj=io.BytesIO(blob)) as bundle:
        assert all(m.isfile() and m.uid == m.gid == m.mtime == 0 for m in bundle)


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        "fixtures/xml/private.xml",
        "services/backend/tests/private.py",
        "services/backend/src/emailmonitor/identity/fixture.py",
        "services/backend/src/emailmonitor/unlisted.py",
        "services/backend/src/emailmonitor/__pycache__/private.pyc",
    ],
)
def test_unlisted_content_never_enters_context_or_archive(xml_inputs: Path, name: str) -> None:
    target = xml_inputs / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SYNTHETIC_DO_NOT_PACKAGE_SENTINEL")
    files = xml_artifacts.collect(xml_inputs, TREE, RUNTIME)
    assert b"SYNTHETIC_DO_NOT_PACKAGE_SENTINEL" not in archive(files)
    assert not any(
        part in {"fixtures", "tests", "__pycache__"} for p in files for part in p.split("/")
    )


@pytest.mark.parametrize("name", ["parsing/xml_worker.py", "fetching/fixture.py", "__init__.py"])
def test_linked_source_refuses_before_materialization(xml_inputs: Path, name: str) -> None:
    path = xml_inputs / "services/backend/src/emailmonitor" / name
    path.unlink()
    path.symlink_to(xml_inputs / "NOTICE.md")
    with pytest.raises(PackagingRefused):
        xml_artifacts.collect(xml_inputs, TREE, RUNTIME)


@pytest.mark.parametrize("tree", ["", "a" * 39, "g" * 40, "a" * 41])
def test_invalid_source_tree_refuses(xml_inputs: Path, tree: str) -> None:
    with pytest.raises(PackagingRefused):
        xml_artifacts.collect(xml_inputs, tree, RUNTIME)


@pytest.mark.parametrize("runtime", [{}, {"bad name": "1.0"}, {"pydantic": "bad/value"}])
def test_invalid_distribution_manifest_refuses(xml_inputs: Path, runtime: dict[str, str]) -> None:
    with pytest.raises(PackagingRefused):
        xml_artifacts.collect(xml_inputs, TREE, runtime)


@pytest.mark.parametrize("mutation", ["source", "manifest", "extra", "missing"])
def test_archive_tampering_refuses(xml_inputs: Path, mutation: str) -> None:
    files = xml_artifacts.collect(xml_inputs, TREE, RUNTIME)
    worker = next(name for name in files if name.endswith("parsing/xml_worker.py"))
    if mutation == "source":
        files[worker] += b"\n# unrecorded mutation\n"
    elif mutation == "manifest":
        manifest = json.loads(files["manifest.json"])
        manifest["production_ready"] = True
        files["manifest.json"] = json.dumps(manifest).encode()
    elif mutation == "extra":
        files["fixtures/private.xml"] = b"not allowed"
    else:
        del files[worker]
    with pytest.raises(PackagingRefused):
        xml_artifacts.verify_archive(archive(files), TREE, RUNTIME)


def test_archive_expected_provenance_cannot_be_swapped(xml_inputs: Path) -> None:
    blob = archive(xml_artifacts.collect(xml_inputs, TREE, RUNTIME))
    with pytest.raises(PackagingRefused):
        xml_artifacts.verify_archive(blob, "b" * 40, RUNTIME)
    with pytest.raises(PackagingRefused):
        xml_artifacts.verify_archive(blob, TREE, {"pydantic": "0.0.0"})


def test_worker_runtime_sources_and_protocol_are_packaged_verbatim(xml_inputs: Path) -> None:
    files = xml_artifacts.collect(xml_inputs, TREE, RUNTIME)
    manifest = json.loads(files["manifest.json"])
    for name in xml_artifacts.XML_FILES:
        matches = [key for key in files if key.endswith("src/emailmonitor/" + name)]
        assert len(matches) == 1
        value = (ROOT / "services/backend/src/emailmonitor" / name).read_bytes()
        assert files[matches[0]] == value
        assert manifest["files"][matches[0]] == {"sha256": digest(value), "bytes": len(value)}


def test_additive_ci_preserves_original_metadata_gate_and_deadline() -> None:
    workflow = (ROOT / ".github/workflows/metadata-packaging.yml").read_text()
    assert "timeout-minutes: 20" in workflow
    assert "contents: read" in workflow
    assert workflow.count("python scripts/packaging/run_acceptance.py") == 1
    assert workflow.count("python scripts/packaging/run_xml_acceptance.py") == 1
    assert workflow.count("EM_REQUIRE_METADATA_PACKAGING: synthetic-test-only") == 2


def test_dockerfile_uses_only_curated_context_in_both_stages() -> None:
    dockerfile = (ROOT / "scripts/packaging/XmlWorker.Dockerfile").read_text()
    assert dockerfile.count(BASE) == 2
    assert "uv==0.12.23 && uv sync --locked --no-dev" in dockerfile
    assert [line for line in dockerfile.splitlines() if line.startswith("COPY ")] == [
        "COPY xml-worker/pyproject.toml xml-worker/uv.lock ./",
        "COPY --from=dependencies /opt/emailmonitor/.venv ./.venv",
        "COPY xml-worker/src ./src",
        "COPY manifest.json ./manifest.json",
        "COPY notices ./notices",
    ]
    assert 'CMD ["python", "-m", "emailmonitor.parsing.xml_worker"]' in dockerfile
    assert "EM_ISOLATION_DIAGNOSTIC=" not in dockerfile
    assert "EXPOSE " not in dockerfile and "VOLUME " not in dockerfile


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE])
def test_nonregular_archive_members_refuse(kind: bytes) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as bundle:
        member = tarfile.TarInfo("manifest.json")
        member.type = kind
        member.linkname = "../../escape"
        member.mode = 0o644
        bundle.addfile(member)
    with pytest.raises(PackagingRefused):
        xml_artifacts.verify_archive(output.getvalue(), TREE, RUNTIME)


@pytest.mark.parametrize("value", [b"", b"not an archive", b"\0" * 10240])
def test_empty_or_invalid_archives_refuse(value: bytes) -> None:
    with pytest.raises(PackagingRefused):
        xml_artifacts.verify_archive(value, TREE, RUNTIME)


def test_probe_source_allowlist_matches_collector() -> None:
    import xml_probe

    assert xml_probe.XML_FILES == xml_artifacts.XML_FILES
    assert xml_probe.NOTICES == NOTICES


@pytest.fixture
def probe_root(xml_inputs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import xml_probe

    target = tmp_path / "image"
    target.mkdir()
    (target / ".venv").mkdir()
    files = xml_artifacts.collect(xml_inputs, TREE, RUNTIME)
    for name, value in files.items():
        if name in {"xml-worker/pyproject.toml", "xml-worker/uv.lock"}:
            continue
        path = target / name.removeprefix("xml-worker/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    class Distribution:
        metadata = {"Name": "pydantic"}
        version = "2.14.0"

    monkeypatch.setattr(xml_probe, "ROOT", target)
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [Distribution()])
    return target


def test_probe_verifies_exact_layout_and_defined_content(probe_root: Path) -> None:
    import xml_probe

    assert xml_probe.verify_layout() == RUNTIME
    first = xml_probe.content_digest()
    assert len(first) == 64
    assert first == xml_probe.content_digest()
    worker = probe_root / "src/emailmonitor/parsing/xml_worker.py"
    worker.write_bytes(worker.read_bytes() + b"\n# change\n")
    assert xml_probe.content_digest() != first
    with pytest.raises(RuntimeError, match="integrity"):
        xml_probe.verify_layout()


@pytest.mark.parametrize("name", ["fixtures/private.xml", "src/private.py", "notices/private.txt"])
def test_probe_refuses_extra_image_content(probe_root: Path, name: str) -> None:
    import xml_probe

    target = probe_root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SYNTHETIC_PRIVATE_SENTINEL")
    with pytest.raises(RuntimeError):
        xml_probe.verify_layout()


@pytest.mark.parametrize(
    "field", ["production_ready", "working_extraction_service", "full_service"]
)
def test_probe_refuses_activation_claim(probe_root: Path, field: str) -> None:
    import xml_probe

    path = probe_root / "manifest.json"
    value = json.loads(path.read_text())
    value[field] = True
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="manifest"):
        xml_probe.verify_layout()


def test_probe_refuses_unrecognized_image_symlink(probe_root: Path) -> None:
    import xml_probe

    (probe_root / ".venv/unknown").symlink_to("/etc/passwd")
    with pytest.raises(RuntimeError, match="link"):
        xml_probe.content_digest()


def test_probe_refuses_runtime_distribution_drift(
    probe_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import xml_probe

    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [])
    with pytest.raises(RuntimeError, match="runtime_closure"):
        xml_probe.verify_layout()


def test_materialized_closure_parses_host_stdin_without_embedded_assets(
    xml_inputs: Path, tmp_path: Path
) -> None:
    from emailmonitor.parsing.xml_channel import fixture_expectation
    from emailmonitor.parsing.xml_protocol import encode_input

    context = tmp_path / "context"
    xml_artifacts.materialize(xml_artifacts.collect(xml_inputs, TREE, RUNTIME), context)
    data = (ROOT / "fixtures/xml/sciencedirect-article.xml").read_bytes()
    code = """
import json, sys
sys.path.insert(0, sys.argv[1])
from emailmonitor.parsing.xml_protocol import parse_input
value = parse_input(sys.stdin.buffer)
print(json.dumps(value.model_dump(mode='json'), sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(context / "xml-worker/src")],
        input=encode_input(data, fixture_expectation()),
        capture_output=True,
        timeout=10,
        check=True,
        cwd=tmp_path,
    )
    assert result.stderr == b""
    observed = json.loads(result.stdout)
    assert observed["content_digest"] == digest(data)
    assert (
        observed["requested_identifier"] == fixture_expectation().requested_identifier.model_dump()
    )
    assert len(observed["authors"]) == 3
    assert len(observed["candidates"]) == 2
    assert not (context / "fixtures").exists()


@pytest.fixture
def worker_record() -> dict[str, object]:
    return {
        "Image": "sha256:" + "a" * 64,
        "Config": {
            "User": "65532:65532",
            "Cmd": ["python", "-m", "emailmonitor.parsing.xml_worker"],
            "Entrypoint": None,
            "Volumes": None,
            "OpenStdin": True,
            "Tty": False,
            "Env": [
                "PATH=/opt/emailmonitor/.venv/bin:/usr/bin",
                "PYTHONPATH=/opt/emailmonitor/src",
                "PYTHONDONTWRITEBYTECODE=1",
                "EM_ISOLATION_DIAGNOSTIC=synthetic-test-only",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "ReadonlyRootfs": True,
            "Memory": 134217728,
            "MemorySwap": 134217728,
            "PidsLimit": 32,
            "NanoCpus": 500000000,
            "Binds": None,
            "Mounts": None,
            "PortBindings": {},
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
            "Ulimits": [
                {"Name": "core", "Hard": 0, "Soft": 0},
                {"Name": "nofile", "Hard": 64, "Soft": 64},
            ],
        },
        "Mounts": [],
        "State": {"Running": False, "ExitCode": 0, "OOMKilled": False, "Error": ""},
    }


def test_worker_inspection_accepts_exact_existing_profile(worker_record: dict[str, object]) -> None:
    import run_xml_acceptance as runner

    runner.validate_worker_container(worker_record, "sha256:" + "a" * 64)
    runner.validate_stopped(worker_record, 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("NetworkMode", "host"),
        ("Privileged", True),
        ("CapAdd", ["NET_ADMIN"]),
        ("CapDrop", []),
        ("SecurityOpt", ["seccomp=unconfined"]),
        ("ReadonlyRootfs", False),
        ("Memory", 268435456),
        ("MemorySwap", -1),
        ("PidsLimit", 0),
        ("NanoCpus", 0),
        ("Binds", ["/tmp:/host"]),
        ("PortBindings", {"80/tcp": [{}]}),
        ("Tmpfs", {}),
        ("Ulimits", []),
    ],
)
def test_worker_inspection_refuses_profile_drift(
    worker_record: dict[str, object], field: str, value: object
) -> None:
    import run_xml_acceptance as runner

    host = worker_record["HostConfig"]
    assert isinstance(host, dict)
    host[field] = value
    with pytest.raises(PackagingRefused):
        runner.validate_worker_container(worker_record, "sha256:" + "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("User", "0:0"),
        ("Cmd", ["sh"]),
        ("Entrypoint", ["sh"]),
        ("Volumes", {"/data": {}}),
        ("OpenStdin", False),
        ("Tty", True),
        ("Env", ["PYTHONPATH=/tmp"]),
    ],
)
def test_worker_inspection_refuses_command_identity_or_environment_drift(
    worker_record: dict[str, object], field: str, value: object
) -> None:
    import run_xml_acceptance as runner

    config = worker_record["Config"]
    assert isinstance(config, dict)
    config[field] = value
    with pytest.raises(PackagingRefused):
        runner.validate_worker_container(worker_record, "sha256:" + "a" * 64)


@pytest.mark.parametrize("extra", ["HTTPS_PROXY=sentinel", "SOURCE_KEY=sentinel", "PATH=duplicate"])
def test_worker_environment_refuses_ambient_or_duplicate_values(
    worker_record: dict[str, object], extra: str
) -> None:
    import run_xml_acceptance as runner

    config = worker_record["Config"]
    assert isinstance(config, dict)
    config["Env"].append(extra)
    with pytest.raises(PackagingRefused):
        runner.validate_worker_container(worker_record, "sha256:" + "a" * 64)


def test_worker_image_identity_cannot_be_swapped(worker_record: dict[str, object]) -> None:
    import run_xml_acceptance as runner

    with pytest.raises(PackagingRefused):
        runner.validate_worker_container(worker_record, "sha256:" + "b" * 64)


@pytest.mark.parametrize(
    "field,value",
    [("Running", True), ("OOMKilled", True), ("ExitCode", 137), ("Error", "private sentinel")],
)
def test_worker_generic_failure_is_never_accepted_as_refusal(
    worker_record: dict[str, object], field: str, value: object
) -> None:
    import run_xml_acceptance as runner

    state = worker_record["State"]
    assert isinstance(state, dict)
    state[field] = value
    with pytest.raises(PackagingRefused, match="^xml_package_worker_exit_refused$"):
        runner.validate_stopped(worker_record, 1)


def test_worker_cases_exercise_actual_protocol_and_matching_digest_grammar() -> None:
    import run_xml_acceptance as runner
    from emailmonitor.fetching.safety import FetchDenied
    from emailmonitor.parsing.xml_protocol import parse_input, read_input

    data = (ROOT / "fixtures/xml/sciencedirect-article.xml").read_bytes()
    cases = runner.worker_cases(data)
    assert [case.name for case in cases] == [
        "valid",
        "malformed_frame",
        "malformed_xml",
        "digest_mismatch",
        "trailing_bytes",
        "dtd",
        "missing_marker",
    ]
    assert cases[0].exit_code == 0 and cases[0].marker
    assert parse_input(io.BytesIO(cases[0].frame)).status == "observed"
    assert cases[-1].frame == cases[0].frame and not cases[-1].marker
    for case in cases[1:-1]:
        assert case.exit_code == 1 and case.marker
        with pytest.raises((ValueError, FetchDenied)):
            parse_input(io.BytesIO(case.frame))
    for case in (cases[2], cases[4], cases[5]):
        # Security/XML grammar cases pass framing/digest validation first.
        payload, expected = read_input(io.BytesIO(case.frame))
        assert expected.content_digest == digest(payload)


def test_bounded_control_reader_preserves_exit_and_separate_streams() -> None:
    import run_xml_acceptance as runner

    result = runner.bounded_process(
        [sys.executable, "-c", "import sys;print('out');sys.stderr.write('err');sys.exit(7)"],
        timeout=2,
    )
    assert result.returncode == 7 and result.stdout == b"out\n" and result.stderr == b"err"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_control_reader_bounds_each_stream_while_running(stream: str) -> None:
    import run_xml_acceptance as runner

    with pytest.raises(PackagingRefused, match="^xml_package_command_output_refused$"):
        runner.bounded_process(
            [
                sys.executable,
                "-c",
                f"import sys,time;sys.{stream}.write('x'*10000);"
                f"sys.{stream}.flush();time.sleep(10)",
            ],
            timeout=2,
            stdout_limit=100,
            stderr_limit=100,
        )


def test_control_reader_timeout_is_sanitized_and_kills_owned_process() -> None:
    import run_xml_acceptance as runner

    with pytest.raises(PackagingRefused, match="^xml_package_command_failed$"):
        runner.bounded_process([sys.executable, "-c", "import time;time.sleep(10)"], timeout=0.05)


def test_control_command_never_exposes_failure_output() -> None:
    import run_xml_acceptance as runner

    with pytest.raises(PackagingRefused, match="^xml_package_command_failed$"):
        runner.command([sys.executable, "-c", "import sys;print('PRIVATE_SENTINEL');sys.exit(1)"])


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "negative_broken_pipe",
        "wrong_stderr",
        "stdout",
        "timeout",
        "oom",
        "wrong_exit",
        "positive_broken_pipe",
    ],
)
def test_full_worker_loop_keeps_positive_and_exact_refusal_predicates(
    worker_record: dict[str, object], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import copy
    from typing import Any

    import run_xml_acceptance as runner
    from emailmonitor.fetching.safety import IsolationUnavailable
    from emailmonitor.parsing.xml_protocol import parse_input

    data = (ROOT / "fixtures/xml/sciencedirect-article.xml").read_bytes()
    cases = {case.name: case for case in runner.worker_cases(data)}
    visited: list[str] = []

    class FakeOwned(runner.OwnedXmlBuilds):
        current = "valid"

        def create(
            self, image_id: str, ordinal: int, case: str, arguments: tuple[str, ...], marker: bool
        ) -> str:
            assert image_id == "sha256:" + "a" * 64 and ordinal == 1
            assert arguments == ("python", "-m", "emailmonitor.parsing.xml_worker")
            assert marker == cases[case].marker
            self.current = case
            visited.append(case)
            return case

        def record(self, name: str) -> dict[str, Any]:
            assert name == self.current
            record = copy.deepcopy(worker_record)
            config, state = record["Config"], record["State"]
            assert isinstance(config, dict) and isinstance(state, dict)
            if not cases[name].marker:
                config["Env"] = [v for v in config["Env"] if not v.startswith("EM_ISOLATION_")]
            state["ExitCode"] = cases[name].exit_code
            if name != "valid" and fault == "oom":
                state["OOMKilled"] = True
            if name != "valid" and fault == "wrong_exit":
                state["ExitCode"] = 137
            return record

    owned = FakeOwned("a" * 32)

    def exchange(arguments: list[str], frame: bytes) -> bytes:
        name = arguments[-1]
        assert frame == cases[name].frame
        if name == "valid":
            if fault == "positive_broken_pipe":
                raise BrokenPipeError("PRIVATE_SENTINEL")
            observed = parse_input(io.BytesIO(frame))
            return (
                json.dumps(
                    {
                        "profile": "network-none-parser-v1",
                        "observation": observed.model_dump(mode="json"),
                    }
                )
                + "\n"
            ).encode()
        if fault == "timeout":
            raise IsolationUnavailable("xml_parser_timeout")
        if fault == "negative_broken_pipe":
            raise BrokenPipeError("PRIVATE_SENTINEL")
        raise IsolationUnavailable("xml_parser_failed")

    def logs(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert arguments == ["docker", "logs", owned.current]
        return subprocess.CompletedProcess(
            arguments,
            0,
            b"PRIVATE_SENTINEL" if fault == "stdout" else b"",
            b"PRIVATE_SENTINEL" if fault == "wrong_stderr" else b"XML_PARSER_REFUSED\n",
        )

    monkeypatch.setattr(runner, "exchange", exchange)
    monkeypatch.setattr(runner, "bounded_process", logs)
    if fault in {"none", "negative_broken_pipe"}:
        assert owned.worker("sha256:" + "a" * 64, 1, data) == list(cases)
        assert visited == list(cases)
    else:
        with pytest.raises(PackagingRefused) as caught:
            owned.worker("sha256:" + "a" * 64, 1, data)
        assert "PRIVATE_SENTINEL" not in str(caught.value)


def test_unknown_owner_is_never_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import Any

    import run_xml_acceptance as runner

    class UnknownOwned(runner.OwnedXmlBuilds):
        def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
            return {"Config": {"Labels": {LABEL: "different-owner"}}}

    owned = UnknownOwned("a" * 32)
    owned.containers.append("synthetic-container")
    commands: list[list[str]] = []

    def command(arguments: list[str], **kwargs: object) -> bytes:
        commands.append(arguments)
        return b""

    monkeypatch.setattr(runner, "command", command)
    with pytest.raises(PackagingRefused, match="cleanup_failed"):
        owned.close()
    assert commands == []


def test_cleanup_continues_owned_reconciliation_after_one_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Any

    import run_xml_acceptance as runner

    remaining = {"first", "second"}
    removed = []

    class FakeOwned(runner.OwnedXmlBuilds):
        def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
            return {"Config": {"Labels": {LABEL: self.owner}}} if name in remaining else None

    def command(arguments: list[str], **kwargs: object) -> bytes:
        name = arguments[-1]
        removed.append(name)
        if name == "second":
            raise PackagingRefused("fixed_failure")
        remaining.remove(name)
        return b""

    owned = FakeOwned("a" * 32)
    owned.containers.extend(["first", "second"])
    monkeypatch.setattr(runner, "command", command)
    with pytest.raises(PackagingRefused, match="cleanup_failed"):
        owned.close()
    assert removed == ["second", "first"] and remaining == {"second"}


def test_create_registers_owned_name_before_ambiguous_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Any

    import run_xml_acceptance as runner

    class FakeOwned(runner.OwnedXmlBuilds):
        def require_image(self, image_id: str) -> None:
            assert image_id == "sha256:" + "a" * 64

        def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
            return None

    owned = FakeOwned("a" * 32)

    def command(arguments: list[str], **kwargs: object) -> bytes:
        assert len(owned.containers) == 1
        assert arguments[arguments.index("--name") + 1] == owned.containers[0]
        assert "--pull=never" in arguments
        raise PackagingRefused("synthetic_ambiguous_create")

    monkeypatch.setattr(runner, "command", command)
    with pytest.raises(PackagingRefused, match="ambiguous_create"):
        owned.create(
            "sha256:" + "a" * 64,
            1,
            "valid",
            ("python", "-m", "emailmonitor.parsing.xml_worker"),
            True,
        )
    assert owned.containers == ["em-xml-" + "a" * 32 + "-1-valid"]


def test_standalone_workflow_entrypoint_imports_then_refuses_non_ci_context() -> None:
    import os
    import re

    workflow = (ROOT / ".github/workflows/metadata-packaging.yml").read_text()
    step = workflow.split(
        "- name: Two uncached XML worker builds and network-none protocol checks\n"
    )[1]
    match = re.search(r"^\s+PYTHONPATH: ([^\n]+)$", step, re.MULTILINE)
    assert match is not None and match.group(1) == "services/backend/src"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GITHUB_ACTIONS", "EM_REQUIRE_METADATA_PACKAGING", "PYTHONPATH", "PATH"}
    }
    env.update(PYTHONPATH=match.group(1), PATH="")
    result = subprocess.run(
        [sys.executable, "scripts/packaging/run_xml_acceptance.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b"XML_PACKAGING_ACCEPTANCE_REFUSED\n"
