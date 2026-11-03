"""Authored synthetic/mock runner checks. No real acquisition or Docker calls."""

import copy
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import run_private_affiliation_diagnostic_once as once
import run_private_sample_once as old
import run_xml_integration as integration
from emailmonitor.parsing import affiliation_diagnostic_channel as channel
from emailmonitor.parsing import private_affiliation_diagnostic as admission
from emailmonitor.parsing import private_sample, xml_channel
from emailmonitor.parsing.affiliation_diagnostic import AffiliationDiagnostic
from test_affiliation_diagnostic_channel import profile

BODY = b"<synthetic>Authored test bytes only.</synthetic>"
IMAGE = "sha256:" + "c" * 64
OWNER = "d" * 32


@pytest.fixture(autouse=True)
def no_real_acquisition(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Real acquisition is prohibited in runner tests")

    monkeypatch.setattr(once, "acquire", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "socket", denied)


def context() -> tuple[dict[str, str], dict[str, Any]]:
    return (
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": once.REPO,
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REF": "refs/pull/44/merge",
            "GITHUB_HEAD_REF": once.HEAD_REF,
            "GITHUB_BASE_REF": once.BASE_REF,
        },
        {
            "action": "opened",
            "number": 44,
            "repository": {"full_name": once.REPO},
            "pull_request": {
                "number": 44,
                "head": {"ref": once.HEAD_REF, "sha": "a" * 40, "repo": {"full_name": once.REPO}},
                "base": {
                    "ref": once.BASE_REF,
                    "sha": once.BASE_SHA,
                    "repo": {"full_name": once.REPO},
                },
            },
        },
    )


def counters() -> AffiliationDiagnostic:
    return AffiliationDiagnostic.model_validate(
        {name: 0 for name in AffiliationDiagnostic.model_fields if name != "profile"}
    )


def success() -> dict[str, Any]:
    return {
        "status": "diagnosed",
        "reasons": [],
        "diagnostic": counters().model_dump(),
        "cleanup_status": "verified",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_EVENT_NAME", "pull_request_target"),
        ("GITHUB_EVENT_NAME", "push"),
        ("GITHUB_EVENT_NAME", "schedule"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_RUN_ATTEMPT", "01"),
        ("GITHUB_REPOSITORY", "foreign/repo"),
        ("GITHUB_REF", "refs/pull/42/merge"),
        ("GITHUB_REF", "refs/pull/45/merge"),
        ("GITHUB_HEAD_REF", "main"),
        ("GITHUB_BASE_REF", "main"),
        ("HTTPS_PROXY", "https://proxy.example"),
        ("http_proxy", "proxy"),
        ("NO_PROXY", "*"),
        ("ALL_PROXY", "proxy"),
        ("DOCKER_HOST", "other"),
        ("DOCKER_CONTEXT", "other"),
        ("DOCKER_TLS_VERIFY", "1"),
        ("DOCKER_CERT_PATH", "/other"),
        ("SSL_CERT_FILE", "/other"),
        ("SSL_CERT_DIR", "/other"),
        ("SSLKEYLOGFILE", "/private/tls.keys"),
        ("REQUESTS_CA_BUNDLE", "/other"),
        ("CURL_CA_BUNDLE", "/other"),
        ("PYTHONHTTPSVERIFY", "0"),
        ("GITHUB_TOKEN", "synthetic-secret"),
        ("GH_TOKEN", "synthetic-secret"),
        ("ELSEVIER_API_KEY", "synthetic-secret"),
        ("ELS_API_KEY", "synthetic-secret"),
        ("ELSEVIER_INSTTOKEN", "synthetic-secret"),
    ],
)
def test_environment_refuses_before_build_or_network(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    environment, event = context()
    environment[key] = value
    calls: list[str] = []
    monkeypatch.setattr(integration, "load_runtime", lambda: calls.append("runtime"))
    assert once.execute(environment, event) == once.refusal("runner_refused", "not_started")
    assert not calls


@pytest.mark.parametrize(
    "mutation",
    [
        "synchronize",
        "reopened",
        "closed",
        "number",
        "bool_number",
        "string_number",
        "pr_number",
        "pr_bool",
        "repository",
        "head_repo",
        "base_repo",
        "base",
        "head",
        "base_sha",
        "head_sha",
        "uppercase_sha",
        "missing",
        "linux",
        "architecture",
    ],
)
def test_exact_event_and_platform_scope(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    environment, event = context()
    pr = event["pull_request"]
    if mutation in {"synchronize", "reopened", "closed"}:
        event["action"] = mutation
    elif mutation in {"number", "bool_number", "string_number"}:
        event["number"] = {"number": 45, "bool_number": True, "string_number": "44"}[mutation]
    elif mutation in {"pr_number", "pr_bool"}:
        pr["number"] = 45 if mutation == "pr_number" else True
    elif mutation == "repository":
        event["repository"]["full_name"] = "foreign/repo"
    elif mutation in {"head_repo", "base_repo"}:
        pr[mutation.split("_")[0]]["repo"]["full_name"] = "foreign/repo"
    elif mutation in {"base", "head"}:
        pr[mutation]["ref"] = "main"
    elif mutation in {"base_sha", "head_sha"}:
        pr[mutation.split("_")[0]]["sha"] = "b" * 39
    elif mutation == "uppercase_sha":
        pr["head"]["sha"] = "A" * 40
    elif mutation == "missing":
        del event["pull_request"]
    elif mutation == "linux":
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
    else:
        monkeypatch.setattr(platform, "machine", lambda: "arm64")
    calls: list[str] = []
    monkeypatch.setattr(integration, "load_runtime", lambda: calls.append("runtime"))
    assert once.execute(environment, event) == once.refusal("runner_refused", "not_started")
    assert not calls


def test_bounded_unchanged_reader_and_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()
    assert once.acquire is old.acquire
    assert once.read_event is old.read_event
    assert once.remove_private is old.remove_private
    path = tmp_path / "event.json"
    for data in (b'{"action":"opened","action":"opened"}', b"x" * 1048577, b"[]"):
        path.write_bytes(data)
        with pytest.raises(old.Refused):
            once.read_event(str(path))
    _, event = context()
    path.write_text(json.dumps(event))
    assert once.read_event(str(path)) == event


def lifecycle(monkeypatch: pytest.MonkeyPatch, fault: str = "") -> tuple[list[str], list[Path]]:
    steps: list[str] = []
    paths: list[Path] = []
    runtime = SimpleNamespace(
        command=lambda *args, **kwargs: b"b" * 40 if fault == "head" else b"a" * 40,
        OwnedXmlBuilds=lambda value: SimpleNamespace(owner=OWNER),
        LABEL="synthetic-owner",
    )
    monkeypatch.setattr(integration, "load_runtime", lambda: runtime)
    monkeypatch.setattr(signal, "alarm", lambda value: 0)

    def prepare(*args: Any) -> tuple[str, dict[str, object]]:
        steps.append("build")
        if fault in {"build", "dirty"}:
            raise RuntimeError("private@example.org /private/path")
        return IMAGE, {}

    class Alias:
        def __init__(self, *args: Any) -> None:
            pass

        def install(self) -> None:
            steps.append("alias")
            if fault == "alias_install":
                raise RuntimeError("private@example.org")

        def verify(self) -> None:
            steps.append("verify")
            if fault == "alias_verify" or (fault == "alias_after" and "evaluate" in steps):
                raise RuntimeError("private@example.org")

    def acquire() -> bytes:
        steps.append("acquire")
        if fault == "acquire":
            raise RuntimeError("private@example.org")
        if fault == "acquire_signal":
            once.interrupted(signal.SIGTERM, None)
        if fault == "acquire_baseexception":
            raise KeyboardInterrupt("private@example.org")
        return BODY

    def evaluate(path: Path, manifest: object) -> dict[str, Any]:
        steps.append("evaluate")
        paths.append(path)
        assert path.read_bytes() == BODY
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert not path.is_relative_to(once.ROOT)
        metadata = profile()
        metadata["Config"]["Labels"] = {runtime.LABEL: OWNER}
        metadata["Image"] = IMAGE
        if fault == "image":
            metadata["Image"] = "sha256:" + "f" * 64
        elif fault == "owner":
            metadata["Config"]["Labels"][runtime.LABEL] = "e" * 32
        elif fault == "label":
            metadata["Config"].pop("Labels")
        elif fault == "profile":
            metadata["HostConfig"]["NetworkMode"] = "bridge"
        elif fault == "command":
            metadata["Config"]["Cmd"] = list(xml_channel.PRIVATE_COMMAND)
        original_metadata = copy.deepcopy(metadata)
        channel.verify_profile(metadata)
        assert metadata == original_metadata
        if fault == "diagnose":
            raise RuntimeError("private@example.org")
        if fault == "diagnose_signal":
            once.interrupted(signal.SIGALRM, None)
        if fault == "diagnose_baseexception":
            raise SystemExit("private@example.org")
        result = counters().model_dump()
        if fault == "result":
            result["private"] = "private@example.org"
        return result

    def reconcile(*args: Any) -> bool:
        steps.append("cleanup")
        assert all(not path.exists() and not path.parent.exists() for path in paths)
        if fault == "cleanup_error":
            raise RuntimeError("private@example.org")
        if fault == "cleanup_deadline":
            raise integration.CleanupDeadline()
        return fault != "cleanup"

    monkeypatch.setattr(integration, "prepare_image", prepare)
    monkeypatch.setattr(integration, "OwnedAlias", Alias)
    monkeypatch.setattr(integration, "reconcile", reconcile)
    monkeypatch.setattr(once, "acquire", acquire)
    monkeypatch.setattr(once, "evaluate", evaluate)
    return steps, paths


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("", ""),
        ("build", "preparation_refused"),
        ("dirty", "preparation_refused"),
        ("alias_install", "preparation_refused"),
        ("alias_verify", "preparation_refused"),
        ("acquire", "acquisition_refused"),
        ("acquire_signal", "acquisition_refused"),
        ("acquire_baseexception", "acquisition_refused"),
        ("diagnose", "diagnostic_refused"),
        ("diagnose_signal", "diagnostic_refused"),
        ("diagnose_baseexception", "diagnostic_refused"),
        ("image", "diagnostic_refused"),
        ("owner", "diagnostic_refused"),
        ("label", "diagnostic_refused"),
        ("profile", "diagnostic_refused"),
        ("command", "diagnostic_refused"),
        ("alias_after", "diagnostic_refused"),
        ("result", "diagnostic_refused"),
        ("cleanup", "cleanup_refused"),
        ("cleanup_error", "cleanup_refused"),
        ("cleanup_deadline", "cleanup_refused"),
    ],
)
def test_lifecycle_closed_result_and_both_cleanup_checks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fault: str, reason: str
) -> None:
    steps, paths = lifecycle(monkeypatch, fault)
    verifier = channel.verify_profile
    normal_verifier = xml_channel.verify_profile
    result = once.execute(*context())
    assert steps[-1] == "cleanup" and channel.verify_profile is verifier
    assert xml_channel.verify_profile is normal_verifier
    assert all(not path.exists() for path in paths)
    if "acquire" in steps:
        assert steps.index("build") < steps.index("acquire")
    assert steps.count("build") == 1 and steps.count("acquire") <= 1
    assert steps.count("evaluate") <= 1 and steps.count("cleanup") == 1
    if reason:
        assert result["status"] == "refused" and result["reasons"] == [reason]
        assert result["diagnostic"] is None
        assert result["cleanup_status"] == (
            "refused" if reason == "cleanup_refused" else "verified"
        )
    else:
        assert result == success()
    encoded = once.encode_result(result)
    assert len(encoded) <= 4096 and encoded.count(b"\n") == 1
    for forbidden in (b"private@", BODY, old.DIGEST.encode(), b"norm-xml", b"10.1016", b"https:"):
        assert forbidden not in encoded
    assert not capsys.readouterr().out and not capsys.readouterr().err


def test_wrong_checkout_stops_before_build(monkeypatch: pytest.MonkeyPatch) -> None:
    steps, _ = lifecycle(monkeypatch, "head")
    assert once.execute(*context()) == once.refusal("runner_refused", "not_started")
    assert not steps


def test_new_manifest_and_scoped_rights(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = once.fixed_manifest()
    assert type(manifest) is admission.PrivateAffiliationDiagnosticManifest
    assert manifest.purpose == admission.PURPOSE == "one-file-private-affiliation-diagnostic"
    assert manifest.sha256 == old.DIGEST == old.DIGEST
    assert manifest.byte_size == old.SIZE == 143976
    assert manifest.revision == old.REVISION and manifest.corpus_path == old.CORPUS_PATH
    assert manifest.requested_identifier.value == "10.1016/j.renene.2013.10.041"
    calls: list[object] = []

    def evaluate(
        path: Path, received: object, rights: object
    ) -> admission.PrivateAffiliationDiagnosticResult:
        assert (
            received is manifest and type(rights) is admission.AffiliationDiagnosticRightsDecision
        )
        assert rights.manifest_digest == manifest.digest()
        assert rights.scope == admission.PURPOSE and rights.disposition == "cleared"
        assert rights.review_reference == once.REVIEW != old.REVIEW
        calls.append(rights)
        return admission.PrivateAffiliationDiagnosticResult("diagnosed", (), counters())

    monkeypatch.setattr(admission, "evaluate_private_affiliation_diagnostic", evaluate)
    assert once.evaluate(tmp_path / "unused", manifest) == counters().model_dump()
    assert len(calls) == 1


def test_old_rights_cannot_admit_new_manifest(tmp_path: Path) -> None:
    manifest = once.fixed_manifest()
    rights = private_sample.RightsDecision(
        manifest.digest(), private_sample.PURPOSE, "cleared", old.REVIEW
    )
    result = admission.evaluate_private_affiliation_diagnostic(
        tmp_path / "absent",
        manifest,
        rights,  # type: ignore[arg-type]
    )
    assert result == admission.PrivateAffiliationDiagnosticResult("refused", ("rights_refused",))


@pytest.mark.parametrize(
    "fault",
    [
        "result_type",
        "result_extra",
        "status",
        "reasons_type",
        "reasons_value",
        "success_reason",
        "refusal_counter",
        "missing_counter",
        "counter_type",
        "counter_extra",
        "counter_bool",
        "counter_negative",
        "counter_large",
        "counter_float",
        "counter_string",
        "profile",
    ],
)
def test_untrusted_admission_output_cannot_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fault: str
) -> None:
    result: Any = admission.PrivateAffiliationDiagnosticResult("diagnosed", (), counters())
    if fault == "result_type":
        result = SimpleNamespace(**result.__dict__)
    elif fault == "result_extra":
        object.__setattr__(result, "private", "private@example.org")
    elif fault == "status":
        object.__setattr__(result, "status", "observed")
    elif fault == "reasons_type":
        object.__setattr__(result, "reasons", [])
    elif fault in {"reasons_value", "success_reason"}:
        object.__setattr__(
            result,
            "reasons",
            ("private@example.org" if fault == "reasons_value" else "diagnostic_refused",),
        )
    elif fault == "refusal_counter":
        object.__setattr__(result, "status", "refused")
        object.__setattr__(result, "reasons", ("diagnostic_refused",))
    elif fault == "missing_counter":
        object.__setattr__(result, "diagnostic", None)
    elif fault == "counter_type":
        object.__setattr__(result, "diagnostic", result.diagnostic.model_dump())
    elif fault == "counter_extra":
        result.diagnostic.__dict__["private"] = "private@example.org"
    elif fault == "profile":
        result.diagnostic.__dict__["profile"] = "network-none-parser-v1"
    else:
        result.diagnostic.__dict__["author_count"] = {
            "counter_bool": True,
            "counter_negative": -1,
            "counter_large": 20001,
            "counter_float": 1.0,
            "counter_string": "1",
        }[fault]
    monkeypatch.setattr(admission, "evaluate_private_affiliation_diagnostic", lambda *args: result)
    with pytest.raises((once.Refused, ValueError)):
        once.evaluate(tmp_path / "unused", once.fixed_manifest())


@pytest.mark.parametrize(
    "reason", ["manifest_refused", "rights_refused", "file_refused", "diagnostic_refused"]
)
def test_admission_refusal_never_returns_counters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reason: Any
) -> None:
    result = admission.PrivateAffiliationDiagnosticResult("refused", (reason,))
    monkeypatch.setattr(admission, "evaluate_private_affiliation_diagnostic", lambda *args: result)
    with pytest.raises(once.Refused):
        once.evaluate(tmp_path / "unused", once.fixed_manifest())


@pytest.mark.parametrize(
    "fault", ["extra", "missing", "status", "reason", "cleanup", "counter", "refusal", "cap"]
)
def test_final_public_schema_is_closed(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    result = success()
    if fault == "extra":
        result["private"] = "private@example.org"
    elif fault == "missing":
        del result["diagnostic"]["profile"]
    elif fault == "status":
        result["status"] = "observed"
    elif fault == "reason":
        result["reasons"] = ["private@example.org"]
    elif fault == "cleanup":
        result["cleanup_status"] = "not_started"
    elif fault == "counter":
        result["diagnostic"]["author_count"] = True
    elif fault == "refusal":
        result["status"] = "refused"
        result["reasons"] = ["diagnostic_refused"]
    else:
        monkeypatch.setattr(once, "MAX_OUTPUT", len(once.encode_result(result)) - 1)
    with pytest.raises((once.Refused, ValueError)):
        once.encode_result(result)


def test_maximum_counter_values_remain_bounded_and_canonical() -> None:
    result = success()
    for name in result["diagnostic"]:
        if name != "profile":
            result["diagnostic"][name] = 20000
    output = once.encode_result(result)
    assert output == json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert len(output) <= 4096


@pytest.mark.parametrize(
    "fault",
    ["first_delete", "interrupted_delete", "persistent_delete", "silent_delete", "deadline"],
)
def test_failed_context_exit_retains_owner_and_reconciles_docker(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    steps, paths = lifecycle(monkeypatch)
    original = tempfile.TemporaryDirectory
    directories: list[Any] = []
    attempts: list[bool] = []

    class Temporary:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            assert kwargs["dir"] == "/tmp"
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
            if fault == "deadline" and len(attempts) > 1:
                raise integration.CleanupDeadline()
            if fault in {"persistent_delete", "deadline"} or len(attempts) == 1:
                if fault == "interrupted_delete":
                    once.interrupted(signal.SIGTERM, None)
                raise OSError("private@example.org cannot delete")
            self.owned.cleanup()

    def reconcile(*args: Any) -> bool:
        steps.append("cleanup")
        assert len(attempts) >= 2 and paths
        return True

    monkeypatch.setattr(tempfile, "TemporaryDirectory", Temporary)
    monkeypatch.setattr(integration, "reconcile", reconcile)
    try:
        result = once.execute(*context())
        assert steps[-1] == "cleanup" and result["status"] == "refused"
        assert result["diagnostic"] is None
        if fault in {"persistent_delete", "silent_delete", "deadline"}:
            assert result == once.refusal("cleanup_refused", "refused")
            assert len(attempts) == (2 if fault == "deadline" else 3)
        else:
            assert result == once.refusal("diagnostic_refused", "verified")
            assert len(attempts) == 2 and not paths[0].parent.exists()
    finally:
        for owned in directories:
            owned.cleanup()


def test_deadline_budgets_and_exclusive_initial_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle(monkeypatch)
    alarms: list[int] = []
    opens: list[int] = []
    original_open = os.open
    monkeypatch.setattr(signal, "alarm", lambda value: alarms.append(value))

    def opened(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if str(path).endswith("sample.norm-xml"):
            assert mode == 0o600
            assert flags & os.O_EXCL and flags & os.O_NOFOLLOW and flags & os.O_CREAT
            opens.append(flags)
        return original_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", opened)
    assert once.execute(*context()) == success()
    assert len(opens) == 1
    assert alarms == [40, 120, 0, 30, 0, 0, 180, 0]


@pytest.mark.parametrize("fault", ["acquire", "build"])
def test_pre_diagnostic_failure_removes_owned_directory(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    lifecycle(monkeypatch, fault)
    original = tempfile.TemporaryDirectory
    directories: list[Path] = []

    def temporary(*args: Any, **kwargs: Any) -> Any:
        created = original(*args, **kwargs)
        directories.append(Path(created.name))
        return created

    monkeypatch.setattr(tempfile, "TemporaryDirectory", temporary)
    result = once.execute(*context())
    assert result["cleanup_status"] == "verified"
    assert len(directories) == (1 if fault == "acquire" else 0)
    assert all(not path.exists() for path in directories)


def test_no_host_xml_parse_or_old_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from emailmonitor.extraction import sciencedirect

    def denied(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Normal parser, old decision and old execution must remain unused")

    for name in ("execute", "main", "fixed_manifest", "evaluate"):
        monkeypatch.setattr(old, name, denied)
    monkeypatch.setattr(sciencedirect, "parse_article", denied)
    lifecycle(monkeypatch)
    assert once.execute(*context()) == success()


@pytest.mark.parametrize("arguments", [[], ["private-path"]])
def test_stdlib_entrypoint_refuses_redacted(arguments: list[str]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(once.ROOT / "scripts/packaging/run_private_affiliation_diagnostic_once.py"),
            *arguments,
        ],
        env={},
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 1 and result.stderr == b""
    assert result.stdout == once.encode_result(once.refusal("runner_refused", "not_started"))


@pytest.mark.parametrize("fault", ["", "acquire", "invalid_result"])
def test_main_emits_once_only_after_cleanup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, fault: str
) -> None:
    steps, _ = lifecycle(monkeypatch, fault)
    environment, event = context()
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    environment["GITHUB_EVENT_PATH"] = str(event_path)
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(sys, "argv", ["runner"])
    if fault == "invalid_result":
        monkeypatch.setattr(once, "execute", lambda *args: {"private": "private@example.org"})
    if fault:
        with pytest.raises(SystemExit) as error:
            once.main()
        assert error.value.code == 1
    else:
        once.main()
    captured = capsys.readouterr()
    assert captured.err == "" and captured.out.count("\n") == 1
    result = json.loads(captured.out)
    if fault == "invalid_result":
        assert result == once.refusal("cleanup_refused", "refused")
    else:
        assert steps[-1] == "cleanup"
        assert result == (once.refusal("acquisition_refused", "verified") if fault else success())
    assert captured.out.encode() == once.encode_result(result)


@pytest.mark.parametrize("boundary", [0, 1, 2, 3, 4, 5])
def test_cleanup_transition_interruption_cannot_skip_docker(
    monkeypatch: pytest.MonkeyPatch, boundary: int
) -> None:
    steps, _ = lifecycle(monkeypatch)
    cleanup_calls = 0
    injected = False

    def alarm(seconds: int) -> int:
        nonlocal cleanup_calls, injected
        if "evaluate" in steps:
            index = cleanup_calls
            cleanup_calls += 1
            if index == boundary and not injected:
                injected = True
                once.interrupted(signal.SIGTERM, None)
        return 0

    monkeypatch.setattr(signal, "alarm", alarm)
    result = once.execute(*context())
    assert injected and steps[-1] == "cleanup" and steps.count("cleanup") == 1
    assert result["cleanup_status"] in {"verified", "refused"}
    if result["cleanup_status"] == "refused":
        assert result == once.refusal("cleanup_refused", "refused")
    else:
        assert result == success()


@pytest.mark.parametrize("phase", ["private", "docker"])
def test_actual_ordinary_signal_is_deferred_through_both_cleanups(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    steps, _ = lifecycle(monkeypatch)
    real_remove = once.remove_private
    original_handler = signal.signal(signal.SIGTERM, once.interrupted)

    def remove(temporary: Any) -> bool:
        if phase == "private":
            os.kill(os.getpid(), signal.SIGTERM)
        return real_remove(temporary)

    def reconcile(*args: Any) -> bool:
        steps.append("cleanup")
        if phase == "docker":
            os.kill(os.getpid(), signal.SIGTERM)
        return True

    monkeypatch.setattr(once, "remove_private", remove)
    monkeypatch.setattr(integration, "reconcile", reconcile)
    try:
        result = once.execute(*context())
        assert steps[-1] == "cleanup"
        assert result == once.refusal("cleanup_refused", "refused")
    finally:
        signal.signal(signal.SIGTERM, original_handler)


def test_unexpected_execution_escape_cannot_claim_not_started(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    environment, event = context()
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    environment["GITHUB_EVENT_PATH"] = str(event_path)
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(sys, "argv", ["runner"])

    def escaped(*args: Any) -> Any:
        raise RuntimeError("private@example.org /private/path")

    monkeypatch.setattr(once, "execute", escaped)
    with pytest.raises(SystemExit) as error:
        once.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.encode() == once.encode_result(once.refusal("cleanup_refused", "refused"))


def test_actual_admission_accepts_only_bound_synthetic_bytes_and_new_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    from emailmonitor.parsing.xml_protocol import XmlExpectation
    from test_affiliation_diagnostic_reproduction import IDENTIFIER, synthetic

    evaluate = once.evaluate
    steps, _ = lifecycle(monkeypatch)
    data = synthetic(reference="cor")
    values = once.fixed_manifest().model_dump()
    values.update(
        revision="a" * 40,
        corpus_path="SourceXML/S0000000000000001.norm-xml",
        evidence_url=f"{admission.REPOSITORY}/blob/{'a' * 40}/SourceXML/S0000000000000001.norm-xml",
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        requested_identifier=IDENTIFIER.model_dump(),
    )
    manifest = admission.PrivateAffiliationDiagnosticManifest.model_validate(values)
    guest_calls: list[bytes] = []

    def acquire() -> bytes:
        steps.append("acquire")
        return data

    def guest(received: bytes, expected: XmlExpectation) -> AffiliationDiagnostic:
        steps.append("guest")
        assert received == data and expected == manifest.expectation()
        record = profile()
        record["Image"] = IMAGE
        record["Config"]["Labels"] = {"synthetic-owner": OWNER}
        channel.verify_profile(record)
        guest_calls.append(received)
        return counters()

    monkeypatch.setattr(once, "evaluate", evaluate)
    monkeypatch.setattr(once, "acquire", acquire)
    monkeypatch.setattr(once, "fixed_manifest", lambda: manifest)
    monkeypatch.setattr(admission, "diagnose_in_container", guest)
    assert once.execute(*context()) == success()
    assert guest_calls == [data] and steps.count("acquire") == 1
    assert steps.index("build") < steps.index("acquire") < steps.index("guest")
    assert steps[-1] == "cleanup"


@pytest.mark.parametrize("fault", ["inside_checkout", "unsafe_mode"])
def test_private_directory_admission_precedes_acquisition(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    steps, _ = lifecycle(monkeypatch)
    original = tempfile.TemporaryDirectory
    directories: list[Path] = []

    def temporary(*args: Any, **kwargs: Any) -> Any:
        if fault == "inside_checkout":
            kwargs["dir"] = once.ROOT
        created = original(*args, **kwargs)
        path = Path(created.name)
        directories.append(path)
        if fault == "unsafe_mode":
            path.chmod(0o755)
        return created

    monkeypatch.setattr(tempfile, "TemporaryDirectory", temporary)
    assert once.execute(*context()) == once.refusal("preparation_refused", "verified")
    assert "acquire" not in steps and steps[-1] == "cleanup"
    assert directories and all(not path.exists() for path in directories)
