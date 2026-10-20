"""Hold one reviewed XML image through fixed synthetic CI consumers, then remove it."""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from run_xml_acceptance import OwnedXmlBuilds

ROOT = Path(__file__).resolve().parents[2]
ALIAS = "emailmonitor-parser-diagnostic:local"
MARKER = "synthetic-test-only"
CONSUMER_SECONDS = {"application": 1200, "transport": 900}
WRAPPER_SECONDS = {"application": 1200, "transport": 1200}
MODES = {
    "application": ("bash", "scripts/check_tenant_foundation.sh"),
    "transport": ("bash", "scripts/packaging/check_xml_transport.sh"),
}


class IntegrationRefused(RuntimeError):
    """Fixed reason only; never command output, credentials or parser data."""


def require_context(environ: Mapping[str, str], mode: str) -> None:
    if (
        mode not in MODES
        or environ.get("GITHUB_ACTIONS") != "true"
        or environ.get("EM_REQUIRE_XML_INTEGRATION") != MARKER
        or any(
            environ.get(name)
            for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
        )
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
    ):
        raise IntegrationRefused("xml_integration_context_refused")


def load_runtime() -> Any:
    # The module and refusal entrypoint load with stdlib alone. Only after the CI
    # guard, resolve reviewed host source explicitly, independent of PYTHONPATH.
    for directory in (ROOT / "services/backend/src", Path(__file__).resolve().parent):
        source = str(directory)
        if source not in sys.path:
            sys.path.insert(0, source)
    import run_xml_acceptance

    return run_xml_acceptance


class OwnedAlias:
    def __init__(self, owned: OwnedXmlBuilds, image_id: str, command: Callable[..., bytes]) -> None:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise IntegrationRefused("xml_integration_image_refused")
        self.owned, self.image_id, self.command = owned, image_id, command
        self.registered = False

    def verify(self) -> None:
        record = self.owned.owned("image", ALIAS)
        if record is None or record.get("Id") != self.image_id:
            raise IntegrationRefused("xml_integration_alias_refused")

    def install(self) -> None:
        self.owned.require_image(self.image_id)
        if self.owned.inspect("image", ALIAS) is not None:
            raise IntegrationRefused("xml_integration_alias_exists")
        # Reconcile the alias even when docker tag returns an ambiguous failure.
        self.registered = True
        self.command(["docker", "image", "tag", self.image_id, ALIAS], timeout=20)
        self.verify()


def prepare_image(runtime: Any, owned: OwnedXmlBuilds) -> tuple[str, dict[str, object]]:
    from base_inventory import validate_base_inventory
    from inventory_probe import inventory_probe

    versions = {
        name: runtime.command([name, "--version"]).decode("ascii").strip()
        for name in ("uv", "pnpm", "node")
    }
    runtime.require_tool_versions(versions)
    # Source must be a tracked, unchanged exact checkout, not a local build with
    # unrecorded edits. Ignored dependency caches remain outside the context.
    if runtime.command(["git", "status", "--porcelain", "--untracked-files=all"], timeout=10):
        raise IntegrationRefused("xml_integration_source_dirty")
    tree = runtime.command(["git", "rev-parse", "HEAD^{tree}"], timeout=10).decode("ascii").strip()
    exported = runtime.command(
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
    versions = runtime.runtime_versions(exported)
    files = runtime.collect(ROOT, tree, versions)
    bundle = runtime.archive(files)
    if runtime.verify_archive(bundle, tree, versions) != files:
        raise IntegrationRefused("xml_integration_archive_refused")
    dockerfile = runtime.read(ROOT, "scripts/packaging/XmlWorker.Dockerfile")
    probe = inventory_probe(ROOT, "xml")
    if dockerfile.count(runtime.BASE.encode()) != 2:
        raise IntegrationRefused("xml_integration_base_refused")
    with tempfile.TemporaryDirectory(prefix="em-xml-integration-") as temporary:
        context = Path(temporary) / "context"
        runtime.materialize(files, context)
        (context / "Dockerfile").write_bytes(dockerfile)
        _, image_id = owned.build(context, 1)
    result = owned.probe(image_id, probe, 1)
    system = validate_base_inventory(result.get("base_inventory"))
    expected = {
        "scope": runtime.SCOPE,
        "synthetic_test_only": True,
        "fixture_assets_absent": True,
        "working_extraction_service": False,
        "full_service": False,
        "production_ready": False,
        "exact_source_closure": True,
        "source_file_count": len(runtime.XML_FILES),
        "interfaces": ["lo"],
        "runtime_distributions": versions,
        "kernel_restrictions": True,
        "network_errno": [101, 101],
        "manifest_sha256": runtime.digest(files["manifest.json"]),
    }
    if (
        {key: result.get(key) for key in expected} != expected
        or set(result) != set(expected) | {"image_content_sha256", "base_inventory"}
        or not isinstance(result["image_content_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", result["image_content_sha256"])
    ):
        raise IntegrationRefused("xml_integration_probe_refused")
    return image_id, {
        "source_tree": tree,
        "declared_base_image": runtime.BASE,
        "declared_platform": "linux/amd64",
        "base_inventory": system,
        "image_id": image_id,
        "manifest_sha256": expected["manifest_sha256"],
        "image_content_sha256": result["image_content_sha256"],
        "archive_sha256": runtime.digest(bundle),
    }


def stop_consumer(process: subprocess.Popen[bytes]) -> None:
    # A fresh session belongs solely to this fixed consumer and its children.
    # Signal only that session; never enumerate or kill unrelated host processes.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def run_consumer(
    mode: str,
    image_id: str,
    owner: str,
    environ: Mapping[str, str],
    verify_alias: Callable[[], None],
) -> None:
    if (
        mode not in MODES
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
        or not re.fullmatch(r"[a-f0-9]{32}", owner)
    ):
        raise IntegrationRefused("xml_integration_consumer_refused")
    environment = {
        **environ,
        "EM_REQUIRE_XML_INTEGRATION": MARKER,
        "EM_EXPECTED_XML_IMAGE_ID": image_id,
        "EM_EXPECTED_XML_IMAGE_OWNER": owner,
    }
    commands = (
        (MODES[mode],)
        if mode == "application"
        else (MODES[mode] + ("transport",), MODES[mode] + ("operator",))
    )
    for arguments in commands:
        verify_alias()
        # Retain existing live CI stdout/stderr and exact shell predicates. No
        # capture buffer, generic CLI command or secret-bearing argv is added.
        with subprocess.Popen(
            arguments,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        ) as process:
            try:
                code = process.wait(timeout=CONSUMER_SECONDS[mode])
                if code:
                    raise IntegrationRefused("xml_integration_consumer_failed")
            finally:
                stop_consumer(process)
        verify_alias()


def register_consumer_containers(owned: OwnedXmlBuilds, alias: OwnedAlias) -> None:
    # Containers created by the unchanged XML channel inherit the unique image
    # label. Reconcile interrupted consumers without pruning unrelated resources.
    from run_acceptance import LABEL

    output = alias.command(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--filter",
            "label=" + LABEL + "=" + owned.owner,
            "--format={{.ID}}",
        ],
        timeout=20,
    )
    lines = output.splitlines()
    if (
        len(lines) > 128
        or len(set(lines)) != len(lines)
        or any(not re.fullmatch(rb"[a-f0-9]{64}", line) for line in lines)
    ):
        raise IntegrationRefused("xml_integration_container_list_refused")
    errors = False
    for line in lines:
        identifier = line.decode("ascii")
        try:
            record = owned.owned("container", identifier)
            if record is None:
                continue
            if record.get("Image") != alias.image_id:
                raise IntegrationRefused("xml_integration_container_identity_refused")
            if identifier not in owned.containers:
                owned.containers.append(identifier)
        except Exception:
            errors = True
    if errors:
        raise IntegrationRefused("xml_integration_container_identity_refused")


class CleanupDeadline(BaseException):
    """Break out of best-effort per-resource cleanup when its fixed budget ends."""


def cleanup_deadline(signum: int, frame: object) -> None:
    raise CleanupDeadline()


def reconcile(owned: OwnedXmlBuilds, alias: OwnedAlias | None) -> bool:
    command = alias.command if alias is not None else load_runtime().command
    errors = False
    image_ids = set(owned.image_ids)
    # Ambiguous builds register their unique tag before Docker returns. Resolve
    # only that exact owned tag when no completed image receipt exists yet.
    for name in owned.images:
        try:
            record = owned.owned("image", name)
            if record is None:
                continue
            identifier = record.get("Id", "")
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier) or (
                owned.image_ids and identifier not in owned.image_ids
            ):
                raise IntegrationRefused("xml_integration_image_refused")
            image_ids.add(identifier)
        except Exception:
            errors = True
    if alias is not None:
        try:
            register_consumer_containers(owned, alias)
        except Exception:
            errors = True
        if alias.registered:
            try:
                alias.verify()
            except Exception:
                errors = True
    # The fixed consumer group has already been stopped and reaped. Delete only
    # full immutable container IDs with matching owner AND owned image identity.
    for name in reversed(list(dict.fromkeys(owned.containers))):
        try:
            record = owned.owned("container", name)
            if record is None:
                continue
            identifier = record.get("Id", "")
            if record.get("Image") not in image_ids or not re.fullmatch(
                r"[a-f0-9]{64}", identifier
            ):
                raise IntegrationRefused("xml_integration_container_identity_refused")
            command(["docker", "container", "rm", "--force", identifier], timeout=20)
            if owned.inspect("container", identifier) is not None:
                raise IntegrationRefused("xml_integration_container_cleanup_refused")
        except Exception:
            errors = True
    # Never pass the mutable compatibility alias to docker image rm. A changed
    # alias cannot redirect immutable-ID deletion at a foreign image. Reject any
    # unexpected additional names attached to this invocation-owned image.
    for identifier in sorted(image_ids):
        try:
            record = owned.owned("image", identifier)
            if record is None:
                continue
            allowed_tags = set(owned.images)
            if alias is not None and alias.registered and alias.image_id == identifier:
                allowed_tags.add(ALIAS)
            tags = record.get("RepoTags")
            if (
                record.get("Id") != identifier
                or not isinstance(tags, list)
                or any(not isinstance(tag, str) for tag in tags)
                or set(tags) - allowed_tags
            ):
                raise IntegrationRefused("xml_integration_image_tags_refused")
            command(["docker", "image", "rm", "--force", identifier], timeout=20)
            if owned.inspect("image", identifier) is not None:
                raise IntegrationRefused("xml_integration_image_cleanup_refused")
        except Exception:
            errors = True
    if alias is not None and alias.registered:
        try:
            if owned.inspect("image", ALIAS) is not None:
                errors = True
        except Exception:
            errors = True
    return not errors


def cleanup(owned: OwnedXmlBuilds, alias: OwnedAlias | None, failed: bool) -> None:
    previous = signal.signal(signal.SIGALRM, cleanup_deadline)
    signal.alarm(180)
    verified = False
    try:
        verified = reconcile(owned, alias)
    except CleanupDeadline:
        pass
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    if not verified:
        print(json.dumps({"xml_integration_owned_cleanup_verified": False}), flush=True)
        if not failed:
            raise IntegrationRefused("xml_integration_cleanup_refused")
    else:
        print(json.dumps({"xml_integration_owned_cleanup_verified": True}), flush=True)


def execute(mode: str, environ: Mapping[str, str]) -> None:
    require_context(environ, mode)
    runtime = load_runtime()
    owned = runtime.OwnedXmlBuilds(uuid4().hex)
    alias: OwnedAlias | None = None
    failed = True
    try:
        image_id, receipt = prepare_image(runtime, owned)
        alias = OwnedAlias(owned, image_id, runtime.command)
        alias.install()
        print(json.dumps({"xml_integration_prepared": receipt}, sort_keys=True), flush=True)
        alias.verify()
        run_consumer(mode, image_id, owned.owner, environ, alias.verify)
        alias.verify()
        failed = False
    finally:
        # Main's deadline cannot interrupt the bounded ownership reconciliation.
        signal.alarm(0)
        cleanup(owned, alias, failed)
    # This attests the fixed checks succeeded; actual parser ID assertions belong
    # to their captured verify_profile callbacks, not to alias checks alone.
    print(
        json.dumps(
            {
                "xml_integration_fixed_checks_passed": mode,
                "image_id": image_id,
                "working_extraction_service": False,
                "production_ready": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def interrupted(signum: int, frame: object) -> None:
    raise IntegrationRefused("xml_integration_interrupted")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    require_context(os.environ, mode)
    os.chdir(ROOT)
    previous = {
        kind: signal.signal(kind, interrupted)
        for kind in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM)
    }
    # Both workflow ceilings are 25 minutes. The application aggregate grew
    # with actual service acceptance; per-test/runtime bounds remain unchanged.
    # Setup and final runner overhead must still fit outside this deadline and
    # the separate 180-second cleanup plus owned consumer stop/reap bounds.
    signal.alarm(WRAPPER_SECONDS[mode])
    try:
        execute(mode, dict(os.environ))
    finally:
        signal.alarm(0)
        for kind, handler in previous.items():
            signal.signal(kind, handler)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("XML_INTEGRATION_REFUSED\n")
        raise SystemExit(1) from None
