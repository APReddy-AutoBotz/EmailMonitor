"""Pure fixed-CI orchestration contracts; actual owned-image integration is separate."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import run_xml_integration as integration

from artifacts import PackagingRefused
from run_acceptance import LABEL

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "sha256:" + "a" * 64
OWNER = "b" * 32
CONTAINER = "c" * 64
ENV = {"GITHUB_ACTIONS": "true", "EM_REQUIRE_XML_INTEGRATION": "synthetic-test-only"}


class FakeOwned:
    owner = OWNER

    def __init__(self) -> None:
        self.images = ["owned:unique"]
        self.containers: list[str] = []
        self.image_ids = {IMAGE}
        image = {"Id": IMAGE, "Config": {"Labels": {LABEL: OWNER}}, "RepoTags": ["owned:unique"]}
        self.records: dict[tuple[str, str], dict[str, Any]] = {
            ("image", IMAGE): image,
            ("image", "owned:unique"): image,
        }
        self.calls: list[list[str]] = []
        self.listed = b""
        self.tag_failure = False
        self.cleanup_failure = False
        self.closed = False

    def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
        return self.records.get((kind, name))

    def owned(self, kind: str, name: str) -> dict[str, Any] | None:
        record = self.inspect(kind, name)
        if record is not None and record["Config"]["Labels"].get(LABEL) != self.owner:
            raise PackagingRefused("package_resource_ownership_refused")
        return record

    def require_image(self, image_id: str) -> None:
        assert image_id == IMAGE

    def command(self, arguments: list[str], **kwargs: object) -> bytes:
        self.calls.append(arguments)
        if arguments[:3] == ["docker", "image", "tag"]:
            image = self.records["image", IMAGE]
            image["RepoTags"].append(integration.ALIAS)
            self.records["image", integration.ALIAS] = image
            if self.tag_failure:
                raise PackagingRefused("package_command_failed")
        elif arguments[:3] == ["docker", "image", "rm"]:
            assert arguments[-1] == IMAGE
            self.closed = True
            if self.cleanup_failure:
                raise PackagingRefused("package_cleanup_failed")
            for key, record in list(self.records.items()):
                if key[0] == "image" and record.get("Id") == IMAGE:
                    del self.records[key]
        elif arguments[:3] == ["docker", "container", "rm"]:
            identifier = arguments[-1]
            for key, record in list(self.records.items()):
                if key[0] == "container" and record.get("Id") == identifier:
                    del self.records[key]
        elif arguments[:3] == ["docker", "container", "ls"]:
            return self.listed
        else:
            raise AssertionError(arguments)
        return b""

    def close(self) -> None:
        self.closed = True
        if self.cleanup_failure:
            raise PackagingRefused("package_cleanup_failed")
        for identifier in self.containers:
            self.records.pop(("container", identifier), None)


def alias_for(owned: FakeOwned) -> integration.OwnedAlias:
    return integration.OwnedAlias(owned, IMAGE, owned.command)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["application", "transport"])
def test_ci_context_accepts_only_fixed_modes(mode: str) -> None:
    integration.require_context(ENV, mode)


@pytest.mark.parametrize(
    "environment,mode",
    [
        ({}, "application"),
        ({**ENV, "GITHUB_ACTIONS": "false"}, "application"),
        ({**ENV, "EM_REQUIRE_XML_INTEGRATION": "true"}, "application"),
        (ENV, "bash"),
        (ENV, ""),
        *[
            ({**ENV, key: "foreign"}, "application")
            for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
        ],
    ],
)
def test_context_refuses_before_runtime_import(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], mode: str
) -> None:
    monkeypatch.setattr(integration, "load_runtime", lambda: pytest.fail("runtime imported"))
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_context_refused$"):
        integration.execute(mode, environment)


def test_standalone_refusal_needs_neither_site_packages_nor_pythonpath() -> None:
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH" and k not in ENV}
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts/packaging/run_xml_integration.py"),
            "application",
        ],
        env=environment,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr == b"XML_INTEGRATION_REFUSED\n"


def test_explicit_host_runtime_load_is_independent_of_pythonpath() -> None:
    code = """
import importlib.util, pathlib
path = pathlib.Path('scripts/packaging/run_xml_integration.py').resolve()
spec = importlib.util.spec_from_file_location('integration_entry', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.require_context({'GITHUB_ACTIONS':'true',
    'EM_REQUIRE_XML_INTEGRATION':'synthetic-test-only'}, 'application')
runtime = module.load_runtime()
assert runtime.COMMAND == ('python', '-m', 'emailmonitor.parsing.xml_worker')
print('explicit-source-runtime-ready')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=ROOT, capture_output=True, timeout=10
    )
    assert result.returncode == 0 and result.stderr == b""
    assert result.stdout == b"explicit-source-runtime-ready\n"


def test_alias_registration_survives_ambiguous_tag_result() -> None:
    owned = FakeOwned()
    owned.tag_failure = True
    alias = alias_for(owned)
    with pytest.raises(PackagingRefused):
        alias.install()
    assert alias.registered
    integration.cleanup(owned, alias, failed=True)  # type: ignore[arg-type]
    assert owned.inspect("image", integration.ALIAS) is None
    assert owned.calls[-1] == ["docker", "image", "rm", "--force", IMAGE]


@pytest.mark.parametrize("owner", [OWNER, "d" * 32])
def test_existing_alias_never_overwritten_or_removed(owner: str) -> None:
    owned = FakeOwned()
    owned.records["image", integration.ALIAS] = {"Id": IMAGE, "Config": {"Labels": {LABEL: owner}}}
    alias = alias_for(owned)
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_alias_exists$"):
        alias.install()
    assert not alias.registered and not owned.calls
    assert owned.inspect("image", integration.ALIAS) is not None


@pytest.mark.parametrize("change", ["image", "owner"])
def test_replaced_alias_is_preserved(change: str) -> None:
    owned = FakeOwned()
    alias = alias_for(owned)
    alias.install()
    record = {"Id": IMAGE, "Config": {"Labels": {LABEL: OWNER}}, "RepoTags": [integration.ALIAS]}
    owned.records["image", IMAGE]["RepoTags"].remove(integration.ALIAS)
    if change == "image":
        record["Id"] = "sha256:" + "d" * 64
    else:
        record["Id"] = "sha256:" + "e" * 64
        record["Config"]["Labels"][LABEL] = "d" * 32  # type: ignore[index]
    owned.records["image", integration.ALIAS] = record
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_cleanup_refused$"):
        integration.cleanup(owned, alias, failed=False)  # type: ignore[arg-type]
    assert owned.inspect("image", integration.ALIAS) is record
    assert ["docker", "image", "rm", "--force", IMAGE] in owned.calls
    assert not any(call[-1] == integration.ALIAS for call in owned.calls if "rm" in call)


def test_lingering_inherited_owner_container_is_registered_for_cleanup() -> None:
    owned = FakeOwned()
    owned.listed = (CONTAINER + "\n").encode()
    owned.records["container", CONTAINER] = {
        "Id": CONTAINER,
        "Image": IMAGE,
        "Config": {"Labels": {LABEL: OWNER}},
    }
    integration.cleanup(owned, alias_for(owned), failed=False)  # type: ignore[arg-type]
    assert owned.closed and owned.containers == [CONTAINER]
    assert owned.inspect("container", CONTAINER) is None
    assert "label=" + LABEL + "=" + OWNER in owned.calls[0]
    assert "--no-trunc" in owned.calls[0]


@pytest.mark.parametrize("field", ["image", "owner"])
def test_foreign_lingering_container_is_preserved_and_fails_cleanup(field: str) -> None:
    owned = FakeOwned()
    owned.listed = (CONTAINER + "\n").encode()
    record = {"Id": CONTAINER, "Image": IMAGE, "Config": {"Labels": {LABEL: OWNER}}}
    if field == "image":
        record["Image"] = "sha256:" + "d" * 64
    else:
        record["Config"]["Labels"][LABEL] = "d" * 32  # type: ignore[index]
    owned.records["container", CONTAINER] = record
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_cleanup_refused$"):
        integration.cleanup(owned, alias_for(owned), failed=False)  # type: ignore[arg-type]
    assert not owned.containers and owned.closed
    assert owned.inspect("container", CONTAINER) is record


@pytest.mark.parametrize("listed", [b"short\n", (CONTAINER + "\n").encode() * 2, b"x\n" * 129])
def test_invalid_container_enumeration_refuses(listed: bytes) -> None:
    owned = FakeOwned()
    owned.listed = listed
    with pytest.raises(
        integration.IntegrationRefused, match="^xml_integration_container_list_refused$"
    ):
        integration.register_consumer_containers(owned, alias_for(owned))  # type: ignore[arg-type]
    assert not owned.containers


def test_cleanup_failure_cannot_turn_a_failed_consumer_into_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    owned = FakeOwned()
    owned.cleanup_failure = True
    runtime = SimpleNamespace(OwnedXmlBuilds=lambda owner: owned, command=owned.command)
    monkeypatch.setattr(integration, "load_runtime", lambda: runtime)
    monkeypatch.setattr(integration, "prepare_image", lambda *args: (IMAGE, {}))
    original = integration.IntegrationRefused("original_consumer_failure")

    def fail(*args: object) -> None:
        raise original

    monkeypatch.setattr(integration, "run_consumer", fail)
    with pytest.raises(integration.IntegrationRefused) as raised:
        integration.execute("application", ENV)
    assert raised.value is original and owned.closed
    output = capsys.readouterr().out
    assert '"xml_integration_owned_cleanup_verified": false' in output
    assert "xml_integration_fixed_checks_passed" not in output


def test_cleanup_deadline_is_failure_and_restores_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = FakeOwned()

    def expired(*args: object) -> bool:
        raise integration.CleanupDeadline()

    monkeypatch.setattr(integration, "reconcile", expired)
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_cleanup_refused$"):
        integration.cleanup(owned, None, failed=False)  # type: ignore[arg-type]


class FakeConsumer:
    pid = 12345

    def __init__(self, failure: BaseException | None = None, code: int = 0) -> None:
        self.failure, self.code = failure, code
        self.waits: list[int] = []

    def __enter__(self) -> "FakeConsumer":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def wait(self, timeout: int) -> int:
        self.waits.append(timeout)
        if self.failure:
            raise self.failure
        return self.code


@pytest.mark.parametrize("mode,count", [("application", 1), ("transport", 2)])
def test_fixed_consumers_stream_and_verify_each_gate(
    monkeypatch: pytest.MonkeyPatch, mode: str, count: int
) -> None:
    commands: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    checks = []
    stops = []

    def popen(arguments: tuple[str, ...], **kwargs: Any) -> FakeConsumer:
        commands.append((arguments, kwargs))
        return FakeConsumer()

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(integration, "stop_consumer", lambda child: stops.append(child))
    integration.run_consumer(
        mode, IMAGE, OWNER, {"EM_EXPECTED_XML_IMAGE_ID": "forged"}, lambda: checks.append(1)
    )
    assert len(commands) == len(stops) == count and len(checks) == count * 2
    for arguments, kwargs in commands:
        assert kwargs["start_new_session"] is True and kwargs["stdin"] == subprocess.DEVNULL
        assert "stdout" not in kwargs and "stderr" not in kwargs and "shell" not in kwargs
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["EM_EXPECTED_XML_IMAGE_ID"] == IMAGE
        assert environment["EM_EXPECTED_XML_IMAGE_OWNER"] == OWNER
        assert environment["EM_REQUIRE_XML_INTEGRATION"] == "synthetic-test-only"
        assert IMAGE not in arguments and OWNER not in arguments
    if mode == "transport":
        assert [arguments[-1] for arguments, _ in commands] == ["transport", "operator"]


@pytest.mark.parametrize("mode,budget", [("application", 1200), ("transport", 900)])
@pytest.mark.parametrize("kind", ["failed", "timeout", "interrupted"])
def test_failed_consumer_is_stopped_before_propagating(
    monkeypatch: pytest.MonkeyPatch, kind: str, mode: str, budget: int
) -> None:
    failure = (
        subprocess.TimeoutExpired("fixed", budget)
        if kind == "timeout"
        else KeyboardInterrupt()
        if kind == "interrupted"
        else None
    )
    child = FakeConsumer(failure, code=1 if kind == "failed" else 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: child)
    stopped = []
    monkeypatch.setattr(integration, "stop_consumer", lambda process: stopped.append(process))
    expected = type(failure) if failure is not None else integration.IntegrationRefused
    with pytest.raises(expected):
        integration.run_consumer(mode, IMAGE, OWNER, ENV, lambda: None)
    assert stopped == [child] and child.waits == [budget]


def test_stop_consumer_signals_only_owned_group_and_reaps(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    child = FakeConsumer()
    monkeypatch.setattr(os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    integration.stop_consumer(child)  # type: ignore[arg-type]
    assert calls == [
        (child.pid, signal.SIGTERM),
        (child.pid, signal.SIGKILL),
    ]
    assert child.waits == [5, 5]


def test_fixed_transport_script_keeps_original_acceptance_predicates() -> None:
    script = (ROOT / "scripts/packaging/check_xml_transport.sh").read_text()
    assert "set -euo pipefail" in script
    assert script.count("uv run --project services/backend pytest") == 4
    assert "test_affiliation_diagnostic_acceptance.py -ra -s" in script
    assert "AFFILIATION_DIAGNOSTIC_SYNTHETIC_NETWORK_NONE_COUNTERS" in script
    assert script.count("(^|[=[:space:]])1 passed([ ,]|$)") == 2
    assert (
        "test_transport_acceptance.py scripts/isolation/test_provider_transport_acceptance.py "
        "scripts/isolation/test_provider_journey_acceptance.py -ra -s" in script
    )
    assert (
        "test_operator_browser_acceptance.py "
        "scripts/isolation/test_operator_keyword_browser_acceptance.py -v -s"
    ) in script
    assert "41 passed([ ,]|$)" in script and "4 passed([ ,]|$)" in script
    assert "[0-9]+ skipped|[0-9]+ warnings?" in script
    assert "NORMAL_OPERATOR_RABBITMQ_PROVIDER_ISOLATED_REVIEW_EXPORT" in script
    assert "NORMAL_OPERATOR_KEYWORD_BROWSER_ISOLATED_REVIEW_EXPORT" in script
    assert "[0-9]+ skipped" in script
    assert "eval " not in script and "bash -c" not in script


def test_preflight_dirty_tree_prevents_build(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def command(arguments: list[str], **kwargs: object) -> bytes:
        calls.append(arguments)
        return b" M unrecorded.py\n" if arguments[:2] == ["git", "status"] else b"tool-version"

    runtime = SimpleNamespace(command=command, require_tool_versions=lambda versions: None)
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_source_dirty$"):
        integration.prepare_image(runtime, FakeOwned())  # type: ignore[arg-type]
    assert len(calls) == 4
    assert not any(args[0] == "docker" for args in calls)


@pytest.mark.parametrize("mutation", ["extra_tag", "owner", "retained_image"])
def test_image_cleanup_refuses_unknown_names_owner_and_incomplete_removal(mutation: str) -> None:
    owned = FakeOwned()
    alias = alias_for(owned)
    alias.install()
    if mutation == "extra_tag":
        owned.records["image", IMAGE]["RepoTags"].append("unrelated:keep")
    elif mutation == "owner":
        owned.records["image", IMAGE]["Config"]["Labels"][LABEL] = "d" * 32
    else:
        owned.cleanup_failure = True
    with pytest.raises(integration.IntegrationRefused, match="^xml_integration_cleanup_refused$"):
        integration.cleanup(owned, alias, failed=False)  # type: ignore[arg-type]
    assert owned.inspect("image", IMAGE) is not None
    if mutation != "retained_image":
        assert not any(call[:3] == ["docker", "image", "rm"] for call in owned.calls)


def test_success_requires_consumer_and_cleanup_before_success_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    owned = FakeOwned()
    runtime = SimpleNamespace(OwnedXmlBuilds=lambda owner: owned, command=owned.command)
    monkeypatch.setattr(integration, "load_runtime", lambda: runtime)
    monkeypatch.setattr(integration, "prepare_image", lambda *args: (IMAGE, {}))
    consumed = []

    def consumer(*args: object) -> None:
        consumed.append(1)
        assert owned.inspect("image", integration.ALIAS) is not None
        assert not owned.closed

    monkeypatch.setattr(integration, "run_consumer", consumer)
    integration.execute("application", ENV)
    assert consumed == [1] and owned.closed
    assert not owned.records
    output = capsys.readouterr().out
    assert output.index('"xml_integration_owned_cleanup_verified": true') < output.index(
        '"xml_integration_fixed_checks_passed": "application"'
    )


@pytest.fixture
def preparation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Any, Any, list[list[str]]]:
    import run_xml_acceptance as real
    from test_base_inventory import valid_base_inventory

    system_inventory = valid_base_inventory(tmp_path / "base")

    calls: list[list[str]] = []

    def command(arguments: list[str], **kwargs: object) -> bytes:
        calls.append(arguments)
        if arguments[0] in ("uv", "pnpm", "node") and arguments[1:] == ["--version"]:
            return {"uv": b"uv 0.12.23", "pnpm": b"11.25.0", "node": b"v24.19.0"}[arguments[0]]
        if arguments[:2] == ["git", "status"]:
            return b""
        if arguments[:2] == ["git", "rev-parse"]:
            return b"a" * 40 + b"\n"
        if arguments[:2] == ["uv", "export"]:
            return b"pydantic==2.14.0\n"
        raise AssertionError(arguments)

    runtime = SimpleNamespace(
        **{
            name: getattr(real, name)
            for name in (
                "BASE",
                "SCOPE",
                "XML_FILES",
                "require_tool_versions",
                "runtime_versions",
                "collect",
                "archive",
                "verify_archive",
                "read",
                "materialize",
                "digest",
            )
        },
        command=command,
    )

    class PreparedOwned(FakeOwned):
        manifest: dict[str, Any]
        mutation: str = ""
        built = False
        probed = False

        def build(self, context: Path, ordinal: int) -> tuple[str, str]:
            assert ordinal == 1
            assert not any(
                part in {"fixtures", "tests"} for p in context.rglob("*") for part in p.parts
            )
            self.manifest = json.loads((context / "manifest.json").read_bytes())
            self.built = True
            return "owned:unique", IMAGE

        def probe(self, identifier: str, probe: str, ordinal: int) -> dict[str, Any]:
            assert identifier == IMAGE and ordinal == 1 and self.built
            self.probed = True
            result = {
                "scope": runtime.SCOPE,
                "synthetic_test_only": True,
                "fixture_assets_absent": True,
                "working_extraction_service": False,
                "full_service": False,
                "production_ready": False,
                "exact_source_closure": True,
                "source_file_count": len(runtime.XML_FILES),
                "interfaces": ["lo"],
                "runtime_distributions": self.manifest["runtime_distributions"],
                "kernel_restrictions": True,
                "network_errno": [101, 101],
                "manifest_sha256": runtime.digest(
                    runtime.collect(ROOT, "a" * 40, {"pydantic": "2.14.0"})["manifest.json"]
                ),
                "image_content_sha256": "c" * 64,
                "base_inventory": system_inventory,
            }
            if self.mutation == "manifest":
                result["manifest_sha256"] = "0" * 64
            elif self.mutation == "runtime":
                result["runtime_distributions"] = {}
            elif self.mutation == "network":
                result["network_errno"] = [0, 0]
            elif self.mutation == "extra":
                result["unexpected"] = True
            elif self.mutation == "content":
                result["image_content_sha256"] = "not-a-digest"
            elif self.mutation == "inventory_missing":
                del result["base_inventory"]
            elif self.mutation == "inventory_invalid":
                result["base_inventory"] = {"inventory_sha256": "a" * 64}
            return result

    return runtime, PreparedOwned(), calls


def test_preparation_verifies_exact_curated_image_before_return(
    preparation: tuple[Any, Any, list[list[str]]],
) -> None:
    runtime, owned, calls = preparation
    identifier, receipt = integration.prepare_image(runtime, owned)
    assert identifier == IMAGE and owned.built and owned.probed
    assert receipt["source_tree"] == "a" * 40 and receipt["image_id"] == IMAGE
    assert calls[3][:2] == ["git", "status"]
    assert calls[4] == ["git", "rev-parse", "HEAD^{tree}"]
    assert "--locked" in calls[5] and "--no-dev" in calls[5]


@pytest.mark.parametrize(
    "mutation",
    [
        "manifest",
        "runtime",
        "network",
        "extra",
        "content",
        "inventory_missing",
        "inventory_invalid",
    ],
)
def test_invalid_probe_never_returns_an_integration_image(
    preparation: tuple[Any, Any, list[list[str]]], mutation: str
) -> None:
    runtime, owned, _ = preparation
    owned.mutation = mutation
    expected_error = (
        "base_inventory_refused"
        if mutation.startswith("inventory_")
        else "xml_integration_probe_refused"
    )
    with pytest.raises(RuntimeError, match="^" + expected_error + "$"):
        integration.prepare_image(runtime, owned)


def test_private_sample_gate_is_separate_and_synthetic_only() -> None:
    script = (ROOT / "scripts/packaging/check_xml_transport.sh").read_text()
    assert "scripts/isolation/test_private_sample_acceptance.py -ra -s" in script
    assert "PRIVATE_OFFLINE_SYNTHETIC_NETWORK_NONE_REDACTED_COUNTS" in script
    assert "1 passed([ ,]|$)" in script
    assert "[0-9]+ skipped|[0-9]+ warnings?" in script


def test_closed_aggregate_budgets_preserve_cleanup_reserve() -> None:
    assert integration.CONSUMER_SECONDS == {"application": 1200, "transport": 900}
    assert integration.WRAPPER_SECONDS == {"application": 1200, "transport": 1200}
    source = Path(integration.__file__).read_text()
    assert "signal.alarm(180)" in source
    assert source.count("process.wait(timeout=5)") == 2
    assert "signal.alarm(WRAPPER_SECONDS[mode])" in source
    root = Path(integration.__file__).resolve().parents[2]
    assert "timeout-minutes: 25" in (root / ".github/workflows/application.yml").read_text()


def test_focused_service_gate_preserves_aggregate_and_browser_evidence() -> None:
    root = Path(integration.__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/service-runtime.yml").read_text()
    assert workflow.count("pytest services/backend/tests/test_service_runtime_broker.py") == 1
    assert "test_service_runtime_broker.py -v --tb=short" in workflow
    assert "EM_TEST_BROKER_CONTAINER: ${{ job.services.rabbitmq.id }}" in workflow
    assert "        timeout-minutes: 5\n" in workflow
    assert "continue-on-error" not in workflow
    assert "steps.service-prerequisites.outcome == 'success'" in workflow
    assert "steps.service-web.outcome == 'success'" in workflow
    assert "!cancelled()" in workflow
    assert workflow.index("Focused actual service broker acceptance") < workflow.index(
        "Installed service API and independent worker operator acceptance"
    )
    assert "pytest services/backend/tests tests" in (root / "scripts/check.sh").read_text()
