"""Pure installed XML harness boundaries, not actual Docker/SQL execution evidence."""

import ast
import asyncio
import hashlib
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest
import test_installed_xml_acceptance as harness

ROOT = Path(__file__).resolve().parents[3]


def environment() -> dict[str, str]:
    return {
        "EM_REQUIRE_XML_INTEGRATION": "synthetic-test-only",
        "EM_REQUIRE_CONTROLLED_NETWORK": "true",
        "EM_EXPECTED_XML_IMAGE_ID": "sha256:" + "a" * 64,
        "EM_EXPECTED_XML_IMAGE_OWNER": "b" * 32,
    }


@pytest.mark.parametrize("key", list(environment()))
@pytest.mark.parametrize("value", ["", "true", "synthetic-test-only ", "sha256:latest"])
def test_installed_xml_requires_all_exact_curated_identity_fields(key: str, value: str) -> None:
    env = environment()
    harness.require_xml_context(env)
    env[key] = value
    if env == environment():
        return
    with pytest.raises(RuntimeError, match="Curated installed XML CI identity required"):
        harness.require_xml_context(env)


def test_installed_xml_gate_precedes_sql_and_topology(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def allowed(env: object) -> None:
        order.append("services")

    def refused(env: object) -> None:
        order.append("xml")
        raise RuntimeError("authored XML guard refusal")

    class Request:
        def getfixturevalue(self, name: str) -> None:
            raise AssertionError("No SQL fixture may be resolved before both guards")

    monkeypatch.setattr(harness, "require_installed_ci", allowed)
    monkeypatch.setattr(harness, "require_xml_context", refused)
    with pytest.raises(RuntimeError, match="authored XML guard refusal"):
        harness.installed_xml_scenario.__wrapped__(Request())  # type: ignore[attr-defined]
    assert order == ["services", "xml"]


@pytest.mark.parametrize("change", ["changed", "missing", "extra", "empty"])
def test_installed_supervisor_must_match_complete_verified_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    source_root = tmp_path / "source"
    installed = tmp_path / "installed"
    suffix = "services/backend/src/emailmonitor"
    source, packaged = source_root / suffix, installed / suffix
    source.mkdir(parents=True)
    packaged.mkdir(parents=True)
    (source / "launcher.py").write_text("trusted = True\n")
    (packaged / "launcher.py").write_text("trusted = True\n")
    monkeypatch.setattr(harness, "ROOT", source_root)
    monkeypatch.setattr(
        inspect, "getsourcefile", lambda _: str(source / "runtime/controlled_launcher.py")
    )
    harness.verify_installed_launcher(installed)
    if change == "changed":
        (source / "launcher.py").write_text("trusted = False\n")
    elif change == "missing":
        (source / "launcher.py").unlink()
    elif change == "extra":
        (source / "extra.py").write_text("pass\n")
    else:
        (source / "launcher.py").unlink()
        (packaged / "launcher.py").unlink()
    with pytest.raises(RuntimeError, match="Installed supervisor source"):
        harness.verify_installed_launcher(installed)


@pytest.mark.parametrize("direct", [None, 0, 1, "true", [], {}])
def test_installed_xml_browser_refuses_ambiguous_input_before_ui(
    direct: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import operator_ui_acceptance

    monkeypatch.setitem(sys.modules, "operator_ui_helpers", operator_ui_acceptance)
    browser = importlib.import_module("installed_xml_browser")

    async def login() -> None:
        raise AssertionError("Rejected setup must not invoke login")

    with pytest.raises(ValueError, match="Fixed installed XML input required"):
        asyncio.run(
            browser.xml_journey(
                None, None, {"direct_article_url": direct}, lambda _: None, login, asyncio.Event()
            )
        )


def test_installed_html_steps_remain_identical_under_separate_branch() -> None:
    source = (ROOT / "scripts/isolation/installed_operator_browser.py").read_text()
    tree = ast.parse(source)
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "controlled_xml"
    )
    xml = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    html = ast.unparse(ast.Module(body=branch.orelse, type_ignores=[]))
    # Frozen AST of the original HTML steps, ignoring indentation/formatting.
    assert (
        hashlib.sha256(
            ast.dump(
                ast.Module(body=branch.orelse, type_ignores=[]), include_attributes=False
            ).encode()
        ).hexdigest()
        == "853426f42fc71fb1408bd2262909afe14429f813ebe3e6ecca7ead61a713f30b"
    )
    assert "xml_journey" in xml
    assert "no-contact.html" not in xml
    assert "completed partial" in html and "no-contact.html" in html
    assert "Myocardial Infarction" in html
    assert "asyncio.timeout(55)" in html and "asyncio.timeout(30)" in html
    assert "await login()" in html
    assert "actual_callback" in source and "foreign_tenant_job_denied" in source
    assert '"cookies" in setup' in source and "add_cookies" not in source


def test_installed_xml_declares_actual_worker_policy_review_export_and_cleanup() -> None:
    source = (ROOT / "scripts/isolation/test_installed_xml_acceptance.py").read_text()
    browser = (ROOT / "scripts/isolation/installed_xml_browser.py").read_text()
    assert "ProviderJourney(" not in source and "monkeypatch" not in source
    assert 'profile="controlled-xml-service-reference"' in source
    assert "service_image_id=service_image_id" in source
    assert "require_packaged_image" in source and "verify_installed_launcher(installed)" in source
    assert "cleanup_resources(" in source and "value.close()" in source
    assert "Confirm approve synthetic policy" in browser
    assert "does not resolve affiliation uncertainty" in browser
    assert 'enumerate(("xlsx", "csv"))' in browser
    assert "Second@example.org" in browser and "beta@example.org" in browser
    assert "LOCK TABLE emailmonitor.association_batches" in source
    assert "wait_event_type='Lock'" in source and "worker.kill()" in source
    assert 'snapshot(fresh)["calls"] == []' in source
    dockerfile = (ROOT / "scripts/isolation/Dockerfile.installed-operator-ui").read_text()
    assert (
        "COPY scripts/isolation/installed_xml_browser.py ./installed_xml_browser.py" in dockerfile
    )
    workflow = (ROOT / ".github/workflows/service-runtime.yml").read_text()
    assert "pytest scripts/isolation/test_installed_operator_acceptance.py" in workflow
    assert "run_xml_integration.py installed" in workflow


def test_crash_barrier_allows_authority_reads_and_targets_owned_batch_insert() -> None:
    source = inspect.getsource(
        harness.test_installed_controlled_xml_post_observation_crash_recovery
    )
    tree = ast.parse(source)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # ACCESS EXCLUSIVE blocks AccessShare while authority functions are planned,
    # preventing the observation this crash test intends to preserve.
    assert "LOCK TABLE emailmonitor.association_batches IN SHARE MODE" in literals
    assert "ACCESS EXCLUSIVE" not in source
    blocked_query = next(value for value in literals if "FROM pg_stat_activity" in value)
    assert "usename=:name AND wait_event_type='Lock'" in blocked_query
    assert "query LIKE 'INSERT INTO emailmonitor.association_batches%'" in blocked_query
    assert ":barrier_pid=ANY(pg_blocking_pids(pid))" in blocked_query
    assert "SELECT pg_backend_pid()" in literals
    assert 'count("article_observations") != 1' in source
    assert "wait_for(committed_and_blocked, seconds=45)" in source
    assert "worker.wait(timeout=5) == 137" in source
    assert 'snapshot(fresh)["calls"] == []' in source
    assert "recovered.parser_calls == 0" in source


@pytest.mark.parametrize("failure", [None, "build", "help", "probe", "work", "cleanup"])
def test_installed_service_image_owned_lifetime_and_failure_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    from contextlib import nullcontext

    import installed_xml_service_image as image

    from artifacts import canonical, digest

    installed = tmp_path / "installed"
    installed.mkdir()
    payload = b"synthetic installed source\n"
    manifest = canonical(
        {
            "scope": "authored-source-service-reference",
            "production_ready": False,
            "source_tree": "a" * 40,
            "runtime_distributions": {"authored": "1.0"},
            "files": {"module.py": {"sha256": digest(payload), "bytes": len(payload)}},
        }
    )
    (installed / "manifest.json").write_bytes(manifest)
    (installed / "module.py").write_bytes(payload)
    calls: list[str] = []
    original = RuntimeError("owned image authored failure")

    class Owner:
        def __init__(self, owner: str) -> None:
            assert len(owner) == 32

        def build(self, context: Path, ordinal: int) -> str:
            calls.append("build")
            assert ordinal == 1
            assert (context / "module.py").read_bytes() == payload
            assert (context / ".dockerignore").read_text() == "migrations\n"
            assert (context / "manifest.json").read_bytes() == manifest
            assert {p.name for p in context.iterdir()} == {
                "module.py",
                "manifest.json",
                "Dockerfile",
                ".dockerignore",
            }
            if failure == "build":
                raise original
            return "sha256:" + "c" * 64

        def smoke(self, identifier: str, ordinal: int, probe: str | None = None) -> bytes:
            assert identifier == "sha256:" + "c" * 64 and ordinal == 1
            if probe is None:
                calls.append("help")
                return b"invalid" if failure == "help" else b"usage: installed\n"
            calls.append("probe")
            if failure == "probe":
                raise original
            return b"authored-probe"

        def probe_budget(self) -> Any:
            return nullcontext()

        def close(self) -> None:
            calls.append("close")
            if failure == "cleanup":
                raise original

    def validate(output: bytes, files: dict[str, bytes], runtime: dict[str, str]) -> None:
        calls.append("validate")
        assert output == b"authored-probe" and files["module.py"] == payload
        assert runtime == {"authored": "1.0"}

    monkeypatch.setattr(image, "OwnedServiceBuilds", Owner)
    monkeypatch.setattr(image, "validate_smoke", validate)
    try:
        with image.installed_service_image(installed, tmp_path / "context") as identifier:
            calls.append("work")
            assert identifier == "sha256:" + "c" * 64
            assert "close" not in calls and calls[-2] == "validate"
            if failure == "work":
                raise original
    except RuntimeError as error:
        assert failure is not None
        if failure != "help":
            assert error is original
    else:
        assert failure is None
    assert calls[-1] == "close" and calls.count("close") == 1
    if failure in {"build", "help", "probe"}:
        assert "work" not in calls


def test_installed_revocation_keeps_existing_held_response_boundaries() -> None:
    source = (ROOT / "scripts/isolation/test_installed_xml_acceptance.py").read_text()
    tree = ast.parse(source)
    test = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_installed_controlled_xml_delegation_revoked_before_response_release"
    )
    body = ast.unparse(test)
    assert "configure(network, 'slow')" in body
    assert "range(50)" in body and "time.monotonic() + 10" in body
    assert "time.monotonic() - calls[0]['received_monotonic'] < 15" in body
    assert "UPDATE emailmonitor.service_delegations" in body
    assert "principal_id=:principal" in body and "id=:grant" in body
    assert "organization_id IN (:org,:other)" in body
    assert "worker.parser_calls == 0" in body
    assert "article_observations" in body and "association_batches" in body
    assert "execution_effects" in body and "len(calls) == 1" in body
    assert "resource_state.state == 'finished'" in body
    assert "resource_state.state == 'active' and resource_state.bounded is True" in body
    assert "monkeypatch" not in body and "ProviderJourney(" not in body


@pytest.mark.parametrize("failure", [None, "send", "reply", "poisoned"])
def test_actual_revocation_release_is_once_only_even_after_ambiguous_failure(
    failure: str | None,
) -> None:
    from types import SimpleNamespace

    source = (ROOT / "scripts/isolation/test_installed_xml_acceptance.py").read_text()
    tree = ast.parse(source)
    test = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_installed_controlled_xml_delegation_revoked_before_response_release"
    )
    release = next(
        node
        for node in ast.walk(test)
        if isinstance(node, ast.FunctionDef) and node.name == "release"
    )
    wrapper = ast.parse("def build():\n    released = False\n    return None\n").body[0]
    assert isinstance(wrapper, ast.FunctionDef)
    wrapper.body[1:] = [release, ast.Return(value=ast.Name(id="release", ctx=ast.Load()))]
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    calls: list[str] = []

    class Fixture:
        poisoned = failure == "poisoned"

        def send(self, value: object, deadline: float) -> None:
            calls.append("send")
            assert value == {"kind": "release"} and deadline == 8.0
            if failure == "send":
                raise RuntimeError("authored uncertain send")

        def receive(self, deadline: float) -> dict[str, str]:
            calls.append("receive")
            assert deadline == 8.0
            return {"kind": "wrong" if failure == "reply" else "released"}

    fixture = Fixture()
    namespace: dict[str, Any] = {
        "network": SimpleNamespace(processes={"fixture-a": fixture}),
        "time": SimpleNamespace(monotonic=lambda: 3.0),
    }
    exec(compile(module, "actual-installed-revocation-release", "exec"), namespace)
    action = namespace["build"]()
    if failure is None:
        action()
        assert calls == ["send", "receive"] and not fixture.poisoned
    else:
        with pytest.raises((RuntimeError, AssertionError)):
            action()
        assert fixture.poisoned
    previous = list(calls)
    action()
    assert calls == previous
