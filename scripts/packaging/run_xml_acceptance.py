"""Owned synthetic XML image builds and actual worker checks; no publication."""

import json
import os
import re
import selectors
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from emailmonitor.extraction.sciencedirect import parse_article
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing.xml_channel import (
    COMMAND,
    PROFILE,
    decode_output,
    exchange,
    fixture_expectation,
    verify_profile,
)
from emailmonitor.parsing.xml_protocol import encode_header, encode_input
from xml_artifacts import SCOPE, XML_FILES, archive, collect, digest, materialize, verify_archive

from artifacts import BASE, PLATFORM, PackagingRefused, read
from run_acceptance import (
    LABEL,
    ROOT,
    OwnedBuilds,
    require_ci,
    require_tool_versions,
    runtime_versions,
    validate_container,
)

MARKER = "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-test-only"
REFUSAL = b"XML_PARSER_REFUSED\n"
ENVIRONMENT_KEYS = {
    "PATH",
    "LANG",
    "GPG_KEY",
    "PYTHON_VERSION",
    "PYTHON_SHA256",
    "PYTHONPATH",
    "PYTHONDONTWRITEBYTECODE",
}


def bounded_process(
    arguments: list[str],
    timeout: float = 30,
    *,
    stdout_limit: int = 131072,
    stderr_limit: int = 4096,
) -> subprocess.CompletedProcess[bytes]:
    """Cap both output streams while the control/build process is still running."""
    try:
        with subprocess.Popen(
            arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as process:
            assert process.stdout is not None and process.stderr is not None
            buffers = {"stdout": bytearray(), "stderr": bytearray()}
            deadline = time.monotonic() + timeout
            try:
                with selectors.DefaultSelector() as selector:
                    for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, name)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise PackagingRefused("xml_package_command_failed")
                        for key, _ in selector.select(remaining):
                            chunk = os.read(key.fd, 8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            buffer = buffers[key.data]
                            buffer.extend(chunk)
                            limit = stdout_limit if key.data == "stdout" else stderr_limit
                            if len(buffer) > limit:
                                raise PackagingRefused("xml_package_command_output_refused")
                    code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                return subprocess.CompletedProcess(
                    arguments, code, bytes(buffers["stdout"]), bytes(buffers["stderr"])
                )
            except BaseException:
                process.kill()
                process.wait(timeout=5)
                raise
    except (OSError, subprocess.TimeoutExpired):
        raise PackagingRefused("xml_package_command_failed") from None


def command(arguments: list[str], timeout: float = 30, limit: int = 131072) -> bytes:
    result = bounded_process(arguments, timeout, stdout_limit=limit, stderr_limit=limit)
    if result.returncode:
        raise PackagingRefused("xml_package_command_failed")
    return result.stdout


def validate_environment(record: dict[str, Any], marker: bool) -> None:
    values = record["Config"].get("Env")
    if not isinstance(values, list) or any(
        not isinstance(value, str) or "=" not in value for value in values
    ):
        raise PackagingRefused("xml_package_environment_refused")
    environment = dict(value.split("=", 1) for value in values)
    if (
        len(environment) != len(values)
        or set(environment) - ENVIRONMENT_KEYS - ({"EM_ISOLATION_DIAGNOSTIC"} if marker else set())
        or environment.get("PYTHONPATH") != "/opt/emailmonitor/src"
        or environment.get("PYTHONDONTWRITEBYTECODE") != "1"
        or (marker and environment.get("EM_ISOLATION_DIAGNOSTIC") != "synthetic-test-only")
        or (not marker and "EM_ISOLATION_DIAGNOSTIC" in environment)
    ):
        raise PackagingRefused("xml_package_environment_refused")


def validate_worker_container(record: dict[str, Any], image_id: str, marker: bool = True) -> None:
    try:
        verify_profile(record)
        validate_environment(record, marker)
        if (
            record.get("Image") != image_id
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
            or record["Config"].get("OpenStdin") is not True
            or record["Config"].get("Tty") is not False
            or record["HostConfig"].get("PortBindings")
        ):
            raise ValueError("Invalid worker image")
    except (ValueError, TypeError, KeyError):
        raise PackagingRefused("xml_package_worker_profile_refused") from None


def validate_stopped(record: dict[str, Any], exit_code: int) -> None:
    state = record.get("State", {})
    if (
        exit_code not in (0, 1)
        or state.get("Running") is not False
        or state.get("ExitCode") != exit_code
        or state.get("OOMKilled") is not False
        or state.get("Error") not in (None, "")
    ):
        raise PackagingRefused("xml_package_worker_exit_refused")


@dataclass(frozen=True)
class WorkerCase:
    name: str
    frame: bytes
    marker: bool = True
    exit_code: int = 1


def worker_cases(data: bytes) -> tuple[WorkerCase, ...]:
    expected = fixture_expectation()
    valid = encode_input(data, expected)

    def frame(value: bytes) -> bytes:
        changed = expected.model_copy(update={"content_digest": digest(value)})
        return encode_input(value, changed)

    wrong_digest = expected.model_copy(update={"content_digest": "0" * 64})
    return (
        WorkerCase("valid", valid, exit_code=0),
        WorkerCase("malformed_frame", b"{}\n" + data),
        WorkerCase("malformed_xml", frame(b"<unclosed>")),
        WorkerCase("digest_mismatch", encode_header(wrong_digest) + data),
        WorkerCase("trailing_bytes", frame(data + b"TRAILING")),
        WorkerCase("dtd", frame(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///no-such-file">]><x/>')),
        WorkerCase("missing_marker", valid, marker=False),
    )


class OwnedXmlBuilds(OwnedBuilds):
    """Reuse ownership tracking/checks; preserve cleanup with bounded control I/O."""

    def __init__(self, owner: str) -> None:
        super().__init__(owner)
        self.image_ids: set[str] = set()

    def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
        if kind not in {"image", "container"}:
            raise PackagingRefused("package_resource_kind_refused")
        result = bounded_process(["docker", kind, "inspect", name], timeout=10)
        if result.returncode:
            expected = {
                f"Error: No such image: {name}",
                f"Error response from daemon: No such image: {name}",
                f"Error: No such container: {name}",
                f"Error: No such object: {name}",
                f"Error response from daemon: No such container: {name}",
            }
            if (
                result.returncode == 1
                and result.stdout.strip() in {b"", b"[]"}
                and result.stderr.decode("utf-8", "replace").strip() in expected
            ):
                return None
            raise PackagingRefused("xml_package_inspect_failed")
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise PackagingRefused("xml_package_inspect_failed") from None
        if (
            result.stderr
            or not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise PackagingRefused("xml_package_inspect_failed")
        return value[0]

    def build(self, context: Path, ordinal: int) -> tuple[str, str]:
        if ordinal not in (1, 2):
            raise PackagingRefused("package_build_ordinal_refused")
        name = f"emailmonitor-xml-prerequisite:{self.owner}-{ordinal}"
        if self.inspect("image", name) is not None:
            raise PackagingRefused("package_resource_exists")
        self.images.append(name)
        command(
            [
                "docker",
                "build",
                "--platform=" + PLATFORM,
                "--no-cache",
                "--pull=false",
                "--label",
                LABEL + "=" + self.owner,
                "--tag",
                name,
                str(context),
            ],
            timeout=300,
            limit=8 * 1024 * 1024,
        )
        record = self.owned("image", name)
        if record is None or not re.fullmatch(r"sha256:[a-f0-9]{64}", record.get("Id", "")):
            raise PackagingRefused("xml_package_built_image_missing")
        if (
            record["Config"].get("User") != "65532:65532"
            or record["Config"].get("Cmd") != list(COMMAND)
            or record["Config"].get("Entrypoint") not in (None, [])
        ):
            raise PackagingRefused("xml_package_image_config_refused")
        validate_environment(record, False)
        identifier: str = record["Id"]
        self.image_ids.add(identifier)
        return name, identifier

    def require_image(self, image_id: str) -> None:
        if image_id not in self.image_ids:
            raise PackagingRefused("xml_package_image_identity_refused")
        record = self.owned("image", image_id)
        if record is None or record.get("Id") != image_id:
            raise PackagingRefused("xml_package_image_identity_refused")

    def create(
        self,
        image_id: str,
        ordinal: int,
        case: str,
        arguments: tuple[str, ...],
        marker: bool,
    ) -> str:
        self.require_image(image_id)
        if ordinal not in (1, 2) or case not in {
            "probe",
            "valid",
            "malformed_frame",
            "malformed_xml",
            "digest_mismatch",
            "trailing_bytes",
            "dtd",
            "missing_marker",
        }:
            raise PackagingRefused("xml_package_case_refused")
        name = f"em-xml-{self.owner}-{ordinal}-{case}"
        if self.inspect("container", name) is not None:
            raise PackagingRefused("package_resource_exists")
        self.containers.append(name)
        output = command(
            [
                "docker",
                "create",
                "--pull=never",
                "--interactive",
                "--name",
                name,
                "--label",
                LABEL + "=" + self.owner,
                *(flag for flag in PROFILE if marker or flag != MARKER),
                image_id,
                *arguments,
            ],
            timeout=20,
        )
        if not re.fullmatch(rb"[a-f0-9]{64}\n", output):
            raise PackagingRefused("xml_package_container_identity_refused")
        return name

    def record(self, name: str) -> dict[str, Any]:
        record = self.owned("container", name)
        if record is None:
            raise PackagingRefused("xml_package_container_missing")
        return record

    def probe(self, image_id: str, probe_text: str, ordinal: int) -> dict[str, Any]:
        arguments = ("python", "-c", probe_text)
        name = self.create(image_id, ordinal, "probe", arguments, marker=False)
        record = self.record(name)
        validate_container(record)
        validate_environment(record, False)
        if (
            record.get("Image") != image_id
            or record["Config"].get("Cmd") != list(arguments)
            or record["Config"].get("Entrypoint") not in (None, [])
            or record["Config"].get("Volumes")
            or record["Config"].get("Tty") is not False
            or record["HostConfig"].get("Mounts")
            or sorted(record["HostConfig"].get("Ulimits", []), key=lambda item: item["Name"])
            != [
                {"Name": "core", "Hard": 0, "Soft": 0},
                {"Name": "nofile", "Hard": 64, "Soft": 64},
            ]
        ):
            raise PackagingRefused("xml_package_probe_profile_refused")
        result = bounded_process(["docker", "start", "--attach", name], stdout_limit=65536)
        validate_stopped(self.record(name), 0)
        if result.returncode or result.stderr:
            raise PackagingRefused("xml_package_probe_failed")
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise PackagingRefused("xml_package_probe_output_refused") from None
        if not isinstance(value, dict):
            raise PackagingRefused("xml_package_probe_output_refused")
        return value

    def worker(self, image_id: str, ordinal: int, data: bytes) -> list[str]:
        passed = []
        expected = fixture_expectation()
        observed = parse_article(data, expected.requested_identifier)
        expected.check_observation(observed)
        if (
            observed.status != "observed"
            or len(observed.authors) != 3
            or len(observed.candidates) != 2
            or [author.first for author in observed.authors] != [True, False, False]
            or [author.corresponding for author in observed.authors] != [None, True, True]
        ):
            raise PackagingRefused("xml_package_fixture_refused")
        for case in worker_cases(data):
            name = self.create(image_id, ordinal, case.name, COMMAND, case.marker)
            validate_worker_container(self.record(name), image_id, case.marker)
            output: bytes | None = None
            failed = False
            try:
                output = exchange(
                    ["docker", "start", "--attach", "--interactive", name], case.frame
                )
            except IsolationUnavailable as error:
                # Timeout/output-limit/control failures are never parser refusals.
                if str(error) != "xml_parser_failed":
                    raise PackagingRefused("xml_package_worker_exchange_refused") from None
                failed = True
            except BrokenPipeError:
                # An early fail-closed guard can exit before Docker accepts stdin.
                # This is evidence only after exact stopped-state/log checks below.
                if case.exit_code != 1:
                    raise PackagingRefused("xml_package_worker_exchange_refused") from None
                failed = True
            validate_stopped(self.record(name), case.exit_code)
            if case.exit_code == 0:
                if failed or output is None or decode_output(output, data, expected) != observed:
                    raise PackagingRefused("xml_package_worker_observation_refused")
            else:
                if not failed or output is not None:
                    raise PackagingRefused("xml_package_worker_refusal_missing")
                logs = bounded_process(["docker", "logs", name], stdout_limit=4096)
                if logs.returncode or logs.stdout or logs.stderr != REFUSAL:
                    raise PackagingRefused("xml_package_worker_refusal_refused")
            passed.append(case.name)
        return passed

    def close(self) -> None:
        # Same owned-only reverse cleanup and absence reconciliation as OwnedBuilds;
        # use the bounded command path for both streams, including daemon failures.
        errors = []
        for kind, names in (("container", self.containers), ("image", self.images)):
            for name in reversed(names):
                try:
                    if self.owned(kind, name) is not None:
                        command(["docker", kind, "rm", "--force", name], timeout=20)
                    if self.inspect(kind, name) is not None:
                        raise PackagingRefused("package_cleanup_incomplete")
                except Exception:
                    errors.append("package_cleanup_failed")
        if errors:
            raise PackagingRefused("package_cleanup_failed")


def main() -> None:
    require_ci(dict(os.environ))
    versions = {
        name: command([name, "--version"]).decode("ascii").strip()
        for name in ("uv", "pnpm", "node")
    }
    require_tool_versions(versions)
    command(["git", "diff", "--exit-code", "HEAD"], timeout=10)
    tree_sha = command(["git", "rev-parse", "HEAD^{tree}"], timeout=10).decode("ascii").strip()
    exported = command(
        [
            "uv",
            "export",
            "--project",
            "services/backend",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
        ]
    ).decode("utf-8")
    runtime = runtime_versions(exported)
    probe_text = read(ROOT, "scripts/packaging/xml_probe.py").decode("utf-8")
    dockerfile = read(ROOT, "scripts/packaging/XmlWorker.Dockerfile")
    data = read(ROOT, "fixtures/xml/sciencedirect-article.xml")
    worker_cases(data)  # Fixture digest verified on host; never enters build context.
    if dockerfile.count(BASE.encode()) != 2:
        raise PackagingRefused("xml_package_base_refused")
    owned = OwnedXmlBuilds(uuid4().hex)
    receipts = []
    try:
        with tempfile.TemporaryDirectory(prefix="em-xml-prerequisite-") as temporary:
            for ordinal in (1, 2):
                command(["git", "diff", "--exit-code", "HEAD"], timeout=10)
                files = collect(ROOT, tree_sha, runtime)
                bundle = archive(files)
                if verify_archive(bundle, tree_sha, runtime) != files:
                    raise PackagingRefused("xml_package_archive_roundtrip_failed")
                context = Path(temporary) / str(ordinal)
                materialize(files, context)
                (context / "Dockerfile").write_bytes(dockerfile)
                # The source context itself is exact, and no probe/tests/fixture
                # assets ever reach either builder or runtime image layers.
                _, identifier = owned.build(context, ordinal)
                smoke = owned.probe(identifier, probe_text, ordinal)
                expected = {
                    "scope": SCOPE,
                    "synthetic_test_only": True,
                    "fixture_assets_absent": True,
                    "working_extraction_service": False,
                    "full_service": False,
                    "production_ready": False,
                    "exact_source_closure": True,
                    "source_file_count": len(XML_FILES),
                    "interfaces": ["lo"],
                    "runtime_distributions": runtime,
                    "kernel_restrictions": True,
                    "network_errno": [101, 101],
                    "manifest_sha256": digest(files["manifest.json"]),
                }
                if (
                    {key: smoke.get(key) for key in expected} != expected
                    or set(smoke) != set(expected) | {"image_content_sha256"}
                    or not re.fullmatch(r"[a-f0-9]{64}", smoke["image_content_sha256"])
                ):
                    raise PackagingRefused("xml_package_probe_output_refused")
                cases = owned.worker(identifier, ordinal, data)
                receipts.append(
                    {
                        "archive_sha256": digest(bundle),
                        "manifest_sha256": digest(files["manifest.json"]),
                        "image_id": identifier,
                        "image_content_sha256": smoke["image_content_sha256"],
                        "worker_cases": cases,
                    }
                )
            if any(
                receipts[0][key] != receipts[1][key]
                for key in ("archive_sha256", "manifest_sha256", "image_content_sha256")
            ):
                raise PackagingRefused("xml_package_reproducibility_refused")
    finally:
        owned.close()
        print(json.dumps({"xml_owned_cleanup_verified": True}), flush=True)
    print(
        json.dumps(
            {
                "scope": SCOPE,
                "source_tree": tree_sha,
                "two_uncached_builds": True,
                "artifacts_equal": True,
                "image_contents_equal": True,
                "runtime_distribution_count": len(runtime),
                "source_file_count": len(XML_FILES),
                "network_none_probes": 2,
                "worker_cases_per_image": 7,
                "cleanup_verified": True,
                "synthetic_test_only": True,
                "fixture_assets_absent": True,
                "working_extraction_service": False,
                "full_service": False,
                "production_ready": False,
                "oci_archive_bit_reproducibility_verified": False,
                "receipts": receipts,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("XML_PACKAGING_ACCEPTANCE_REFUSED\n")
        raise SystemExit(1) from None
