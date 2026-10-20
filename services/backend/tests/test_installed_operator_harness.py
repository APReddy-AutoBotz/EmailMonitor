"""Pure refusal/TLS tests for the separately required installed operator CI gate."""

import base64
import hashlib
import json
import ssl
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from api_client import APIClient
from emailmonitor.identity.oidc import AuthenticationDenied
from emailmonitor.runtime.api_entrypoint import ReferenceExchange, ReferenceIdentity
from installed_operator_issuer import synthetic_issuer
from installed_operator_relay import CHUNK, application, validate_target
from test_installed_operator_acceptance import require_installed_ci
from test_service_api_entrypoint import certificate

API = "https://127.0.0.1:4444"
ISSUER = "https://127.0.0.1:4445"
ASSETS = {"index.html": "a" * 64, "assets/index-12345678.js": "b" * 64}


def request(target: str = API + "/api/v1/auth/session") -> dict[str, object]:
    return {"target": target, "method": "GET", "headers": {}, "body": "", "offset": None}


def test_installed_local_missing_services_are_an_explicit_skip() -> None:
    with pytest.raises(pytest.skip.Exception, match="disposable PostgreSQL and RabbitMQ"):
        require_installed_ci({})
    with pytest.raises(pytest.fail.Exception, match="prerequisites unavailable"):
        require_installed_ci({"EM_REQUIRE_INSTALLED_OPERATOR": "true"})


def test_installed_context_refuses_other_accounts_before_sql_setup() -> None:
    with pytest.raises(RuntimeError, match="Exact existing disposable"):
        require_installed_ci(
            {
                "GITHUB_ACTIONS": "true",
                "EM_REQUIRE_INSTALLED_OPERATOR": "true",
                "EM_REQUIRE_OPERATOR_UI": "true",
                "EM_TEST_DISPOSABLE_BROKER": "true",
                "EM_TEST_ADMIN_DATABASE_URL": "postgresql://different.example/database",
                "EM_TEST_AUTH_DATABASE_URL": "postgresql://different.example/database",
                "EM_TEST_DATABASE_URL": "postgresql://different.example/database",
                "EM_TEST_BROKER_URL": "pyamqp://different.example//",
            }
        )


@pytest.mark.parametrize(
    "target",
    [
        "https://example.org/api/v1/auth/session",
        "http://127.0.0.1:4444/api/v1/auth/session",
        "https://127.0.0.1:4446/api/v1/auth/session",
        "https://user@127.0.0.1:4444/api/v1/auth/session",
        API + "/api/v1/../secret",
        API + "/api/v1/%2e%2e/secret",
        API + "/api/v1/auth/session#x",
        API + "/secret",
        ISSUER + "/token",
    ],
)
def test_installed_relay_refuses_nonexact_endpoints(target: str) -> None:
    with pytest.raises(ValueError):
        validate_target(request(target), API, ISSUER, ASSETS)


@pytest.mark.parametrize(
    "headers",
    [
        {"authorization": "Bearer authored"},
        {"cookie": "line\nbreak"},
        {"origin": ISSUER},
        {"x-csrf-token": "x" * 4097},
    ],
)
def test_installed_relay_refuses_unreviewed_headers(headers: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        validate_target({**request(), "headers": headers}, API, ISSUER, ASSETS)


def test_installed_issuer_relay_cannot_receive_application_cookie() -> None:
    with pytest.raises(ValueError, match="credentials"):
        validate_target(
            {**request(ISSUER + "/authorize"), "headers": {"cookie": "test"}}, API, ISSUER, ASSETS
        )


@pytest.mark.parametrize("offset", [-1, True, 1, 1_048_577, None])
def test_installed_asset_ranges_are_bounded(offset: object) -> None:
    with pytest.raises(ValueError):
        validate_target({**request(API + "/"), "offset": offset}, API, ISSUER, ASSETS)


def test_installed_asset_range_and_request_key_order() -> None:
    value = {**request(API + "/assets/index-12345678.js"), "offset": CHUNK}
    shuffled = dict(reversed(list(value.items())))
    target, method, headers, body = validate_target(shuffled, API, ISSUER, ASSETS)
    assert target == value["target"] and method == "GET" and body == ""
    assert headers == {"range": f"bytes={CHUNK}-{2 * CHUNK - 1}"}
    with pytest.raises(ValueError):
        validate_target({**request(), "offset": 0}, API, ISSUER, ASSETS)


def authorize_query(verifier: str) -> dict[str, str]:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return {
        "response_type": "code",
        "client_id": "installed-operator-test",
        "redirect_uri": API + "/auth/complete",
        "scope": "openid",
        "state": "synthetic-state",
        "nonce": "synthetic-nonce",
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
    }


def test_installed_relay_and_reference_exchange_verify_real_tls_pkce_and_nonce(
    tmp_path: Path,
) -> None:
    with synthetic_issuer(tmp_path, API + "/auth/complete", "synthetic-owner") as issuer:
        app = application(API, issuer.origin, issuer.ca, ASSETS, [])
        target = issuer.origin + "/authorize?" + urlencode(authorize_query("v" * 43))
        with APIClient(app, "https://app.example.test") as client:
            response = client.post("/api/v1/installed-relay", json=request(target))
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["status"] == 303
        code = parse_qs(urlsplit(envelope["headers"]["location"]).query)["code"][0]
        identity = ReferenceIdentity(
            issuer=issuer.origin,
            client_id="installed-operator-test",
            authorization_endpoint=issuer.origin + "/authorize",
            token_endpoint=issuer.origin + "/token",
            redirect_uri=API + "/auth/complete",
            verification_keys={"ephemeral": issuer.public_key},
            certificate_authority=issuer.ca,
        )
        token = ReferenceExchange(identity).exchange(code, "v" * 43, identity.redirect_uri)
        claims = jwt.decode(
            token,
            issuer.public_key,
            algorithms=["RS256"],
            audience=identity.client_id,
            issuer=issuer.origin,
        )
        assert claims["sub"] == "synthetic-owner" and claims["nonce"] == "synthetic-nonce"
        assert issuer.authorizations == issuer.exchanges == 1 and issuer.refusals == 0
        with pytest.raises(AuthenticationDenied):
            ReferenceExchange(identity).exchange(code, "v" * 43, identity.redirect_uri)
        assert issuer.exchanges == 1 and issuer.refusals == 1


def test_installed_issuer_wrong_verifier_consumes_code(tmp_path: Path) -> None:
    with synthetic_issuer(tmp_path, API + "/auth/complete", "synthetic-owner") as issuer:
        context = ssl.create_default_context(cafile=str(issuer.ca))
        with httpx.Client(verify=context, trust_env=False, follow_redirects=False) as client:
            response = client.get(issuer.origin + "/authorize", params=authorize_query("v" * 43))
            code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
            payload = {
                "grant_type": "authorization_code",
                "client_id": "installed-operator-test",
                "code": code,
                "code_verifier": "wrong",
                "redirect_uri": API + "/auth/complete",
            }
            assert client.post(issuer.origin + "/token", data=payload).status_code == 400
            payload["code_verifier"] = "v" * 43
            assert client.post(issuer.origin + "/token", data=payload).status_code == 400
        assert issuer.exchanges == 0 and issuer.refusals == 2


def test_installed_relay_refuses_untrusted_certificate(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    wrong_ca, _ = certificate(other)
    with synthetic_issuer(tmp_path, API + "/auth/complete", "synthetic-owner") as issuer:
        app = application(API, issuer.origin, wrong_ca, ASSETS, [])
        target = issuer.origin + "/authorize?" + urlencode(authorize_query("v" * 43))
        with (
            APIClient(app, "https://app.example.test") as client,
            pytest.raises(httpx.ConnectError),
        ):
            client.post("/api/v1/installed-relay", json=request(target))
        assert issuer.authorizations == issuer.exchanges == 0


def test_installed_browser_image_keeps_original_security_profile_and_no_assets_copy() -> None:
    root = Path(__file__).resolve().parents[3]
    launcher = (root / "scripts/isolation/run_installed_operator.py").read_text()
    original = (root / "scripts/isolation/run_operator_ui_acceptance.py").read_text()
    for flag in (
        '"--network=none"',
        '"--cap-drop=ALL"',
        '"--security-opt=no-new-privileges"',
        '"--read-only"',
        '"--user=1000:1000"',
        '"--memory=512m"',
        '"--pids-limit=128"',
        '"--tmpfs=/tmp:rw,noexec,nosuid,size=256m"',
    ):
        assert flag in launcher and flag in original
    assert "from run_operator_ui_acceptance import conversation, validate_guest" in launcher
    dockerfile = (root / "scripts/isolation/Dockerfile.installed-operator-ui").read_text()
    assert "ignore_https_errors" not in dockerfile
    assert "COPY apps/web/dist" not in dockerfile  # Browser fetches the installed HTTPS assets.
    assert "USER 1000:1000" in dockerfile
    guest = (root / "scripts/isolation/installed_operator_browser.py").read_text()
    assert "add_cookies" not in guest and "ignore_https_errors" not in guest
    assert '"cookies" in setup' in guest
    assert 'parsed.path == "/auth/complete"' in guest
    assert "chromium_sandbox=True" in guest
    assert '"https://synthetic.publisher.example/no-contact.html"' in guest
    assert '"1 of 1 discovered article units terminal"' in guest
    assert '"url_no_contact": True' in guest
    assert 'name="no contact", exact=True' in guest
    assert json.loads(json.dumps(ASSETS)) == ASSETS


@pytest.mark.parametrize("primary_exists", [False, True])
@pytest.mark.parametrize("join_mode", ["raises", "alive"])
def test_installed_cleanup_attempts_all_resources_and_preserves_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    primary_exists: bool,
    join_mode: str,
) -> None:
    import threading
    from typing import cast
    from unittest.mock import MagicMock
    from uuid import uuid4

    import test_installed_operator_acceptance as harness
    from sqlalchemy import Engine

    events: list[str] = []
    stop = MagicMock(spec=threading.Event)
    stop.set.side_effect = lambda: events.append("stop")
    thread = MagicMock(spec=threading.Thread)
    thread.ident = 1

    def join(*, timeout: int) -> None:
        assert timeout == 25
        events.append("join")
        if join_mode == "raises":
            raise RuntimeError("private-join-sentinel")

    thread.join.side_effect = join
    thread.is_alive.return_value = True
    app = MagicMock()
    app.close.side_effect = lambda: events.append("app-close")
    admin = MagicMock(spec=Engine)
    statements: list[str] = []

    def execute(statement: object, parameters: dict[str, object]) -> None:
        value = str(statement)
        statements.append(value)
        if len(statements) == 1:
            raise RuntimeError("private-sql-sentinel")

    admin.begin.return_value.__enter__.return_value.execute.side_effect = execute

    def dispose() -> None:
        events.append("admin-dispose")
        raise RuntimeError("private-dispose-sentinel")

    admin.dispose.side_effect = dispose
    bad_path = MagicMock(spec=Path)
    bad_path.unlink.side_effect = RuntimeError("private-config-sentinel")
    actual_path = tmp_path / "second.json"
    actual_path.write_text("synthetic-only")
    org = uuid4()
    principals = {"worker": uuid4(), "publisher": uuid4()}
    names = {kind: "em_installed_" + uuid4().hex for kind in principals}

    def close(application: object, namespace: str) -> None:
        assert application is app and namespace == "em-fixture-" + org.hex
        events.append("broker-close")
        raise RuntimeError("private-broker-sentinel")

    monkeypatch.setattr(harness, "close_owned", close)
    primary = ValueError("original-task-failure") if primary_exists else None

    def cleanup() -> None:
        harness.cleanup_resources(
            stop,
            thread,
            app,
            admin,
            org,
            principals,
            names,
            {"first": cast(Path, bad_path), "second": actual_path},
            primary,
        )

    if primary is not None:
        cleanup()
        assert len(primary.__notes__) == 1
        receipt = primary.__notes__[0]
        assert str(primary) == "original-task-failure"
    else:
        with pytest.raises(RuntimeError, match="Installed operator cleanup failed") as caught:
            cleanup()
        receipt = str(caught.value)
    assert events == ["stop", "join", "broker-close", "app-close", "admin-dispose"]
    assert len(statements) == 12  # Five independent steps per principal and both exact roles.
    assert statements[-2:] == ["DROP ROLE IF EXISTS " + value for value in names.values()]
    assert not actual_path.exists() and bad_path.unlink.call_count == 1
    assert all(
        category in receipt
        for category in (
            "publisher-join",
            "broker-owned-queues",
            "worker-admission_requests",
            "admin-dispose",
            "first-config",
        )
    )
    assert "private-" not in receipt


@pytest.mark.parametrize("primary_exists", [False, True])
@pytest.mark.parametrize("kill_fails", [False, True])
def test_installed_forced_shutdown_fails_success_and_reaps_during_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    primary_exists: bool,
    kill_fails: bool,
) -> None:
    import subprocess
    from unittest.mock import MagicMock

    import test_installed_operator_acceptance as harness

    running = MagicMock()
    running.poll.return_value = None
    running.wait.side_effect = [subprocess.TimeoutExpired("owned", 5), 0]
    if kill_fails:
        running.kill.side_effect = RuntimeError("private-process-sentinel")
    monkeypatch.setattr(
        "test_installed_operator_acceptance.subprocess.Popen", MagicMock(return_value=running)
    )
    primary = ValueError("original-task-failure")
    if primary_exists:
        with pytest.raises(ValueError) as caught:
            with harness.process(tmp_path, "worker", tmp_path / "owned.json"):
                raise primary
        assert caught.value is primary
        assert "process-forced-kill" in primary.__notes__[0]
        receipt = primary.__notes__[0]
    else:
        with pytest.raises(RuntimeError, match="process-forced-kill") as failure:
            with harness.process(tmp_path, "worker", tmp_path / "owned.json"):
                pass
        receipt = str(failure.value)
    assert running.terminate.call_count == running.kill.call_count == 1
    assert running.wait.call_count == 2
    assert ("process-kill" in receipt) is kill_fails
    assert "private-process-sentinel" not in receipt


def test_installed_graceful_process_shutdown_remains_successful(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    import test_installed_operator_acceptance as harness

    running = MagicMock()
    running.poll.return_value = None
    running.wait.return_value = 0
    monkeypatch.setattr(
        "test_installed_operator_acceptance.subprocess.Popen", MagicMock(return_value=running)
    )
    with harness.process(tmp_path, "worker", tmp_path / "owned.json") as owned:
        assert owned is running
    running.terminate.assert_called_once()
    running.wait.assert_called_once_with(timeout=5)
    running.kill.assert_not_called()


@pytest.mark.parametrize("primary_exists", [False, True])
@pytest.mark.parametrize(
    "action,initial,waited",
    [
        ("worker", 7, None),
        ("api", 7, None),
        ("worker", None, 7),
        ("api", None, 7),
        ("worker", None, -15),
        ("api", -15, None),
        ("api", None, -9),
    ],
)
def test_installed_nonzero_process_status_cannot_hide_during_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    primary_exists: bool,
    action: str,
    initial: int | None,
    waited: int | None,
) -> None:
    from typing import Literal, cast
    from unittest.mock import MagicMock

    import test_installed_operator_acceptance as harness

    running = MagicMock()
    running.poll.return_value = initial
    running.wait.return_value = waited
    monkeypatch.setattr(
        "test_installed_operator_acceptance.subprocess.Popen", MagicMock(return_value=running)
    )
    primary = ValueError("original-task-failure")
    command = cast(Literal["api", "worker"], action)
    if primary_exists:
        with pytest.raises(ValueError) as caught:
            with harness.process(tmp_path, command, tmp_path / "owned.json"):
                raise primary
        assert caught.value is primary
        assert "process-exit-status" in primary.__notes__[0]
    else:
        with pytest.raises(RuntimeError, match="process-exit-status"):
            with harness.process(tmp_path, command, tmp_path / "owned.json"):
                pass
    assert running.terminate.call_count == int(initial is None)
    assert running.wait.call_count == int(initial is None)
    running.kill.assert_not_called()


@pytest.mark.parametrize("terminate_fails", [False, True])
def test_installed_api_signal_replay_requires_our_successful_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminate_fails: bool,
) -> None:
    import inspect
    import signal
    from unittest.mock import MagicMock

    import test_installed_operator_acceptance as harness
    from uvicorn.server import Server

    # Verify the pinned runtime behavior that justifies this narrow allowance.
    assert "signal.raise_signal(captured_signal)" in inspect.getsource(Server.capture_signals)
    running = MagicMock()
    running.poll.return_value = None
    running.wait.return_value = -signal.SIGTERM
    if terminate_fails:
        running.terminate.side_effect = RuntimeError("private-terminate-sentinel")
    monkeypatch.setattr(
        "test_installed_operator_acceptance.subprocess.Popen", MagicMock(return_value=running)
    )
    if terminate_fails:
        with pytest.raises(RuntimeError, match="process-terminate,process-exit-status"):
            with harness.process(tmp_path, "api", tmp_path / "owned.json"):
                pass
    else:
        with harness.process(tmp_path, "api", tmp_path / "owned.json"):
            pass
    running.terminate.assert_called_once()
    running.wait.assert_called_once_with(timeout=5)
    running.kill.assert_not_called()
