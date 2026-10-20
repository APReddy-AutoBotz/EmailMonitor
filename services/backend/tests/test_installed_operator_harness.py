"""Pure refusal/TLS tests for the separately required installed operator CI gate."""

import asyncio
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
from installed_operator_redirects import (
    ERROR_DOCUMENT,
    FLOW_COOKIE,
    NAVIGATION,
    InstalledDiagnostics,
    LoginRedirects,
)
from installed_operator_relay import CHUNK, application, validate_target
from test_installed_operator_acceptance import require_installed_ci
from test_service_api_entrypoint import certificate

API = "https://127.0.0.1:4444"
ISSUER = "https://127.0.0.1:4445"
ASSETS = {"index.html": "a" * 64, "assets/index-12345678.js": "b" * 64}


def bound_redirects() -> LoginRedirects:
    coordinator = LoginRedirects(API, ISSUER)
    coordinator.bind_frame("main")
    return coordinator


def login_headers() -> dict[str, str]:
    query = {
        **authorize_query("v" * 43),
        "state": "s" * 43,
        "nonce": "n" * 43,
    }
    return {
        "location": ISSUER + "/authorize?" + urlencode(query),
        "set-cookie": (
            FLOW_COOKIE + "=" + "s" * 43 + "; HttpOnly; Max-Age=300; Path=/; SameSite=lax; Secure"
        ),
        "cache-control": "no-store",
        "content-type": "text/html",
    }


def arm_login(coordinator: LoginRedirects, original: object) -> dict[str, str]:
    headers = login_headers()
    coordinator.arm(
        original,
        source=API + "/api/v1/auth/start",
        method="GET",
        main_frame=True,
        redirected_from=None,
        status=303,
        headers=headers,
    )
    return headers


def observe_redirect(coordinator: LoginRedirects, original: object, target: str) -> None:
    coordinator.observe_failure(
        target=target,
        method="GET",
        main_frame=True,
        redirected_from=original,
        failure="net::ERR_CONNECTION_REFUSED",
    )
    coordinator.observe_commit(
        frame="main",
        loader="loader-" + str(coordinator.redirects),
        url=ERROR_DOCUMENT,
        target=target,
    )
    coordinator.observe_lifecycle(
        frame="main",
        loader="loader-" + str(coordinator.redirects),
        name="DOMContentLoaded",
    )
    coordinator.observe_public_commit(
        sequence=coordinator.redirects,
        main_frame=True,
        url=ERROR_DOCUMENT,
    )
    coordinator.observe_public_loaded(sequence=coordinator.redirects)


async def synthetic_login(coordinator: LoginRedirects) -> None:
    coordinator.begin()
    original = object()
    headers = arm_login(coordinator, original)
    unchanged = dict(headers)
    # Browser receives these exact headers and real 303 after observation is armed.
    waiting = asyncio.create_task(coordinator.next_target())
    await asyncio.sleep(0)
    assert not waiting.done()
    observe_redirect(coordinator, original, headers["location"])
    authorization = await waiting
    assert headers == unchanged
    callback = API + "/auth/complete?" + urlencode({"state": "s" * 43, "code": "c" * 32})
    issuer_request = object()
    coordinator.arm(
        issuer_request,
        source=authorization,
        method="GET",
        main_frame=True,
        redirected_from=None,
        status=303,
        headers={"location": callback, "content-type": "application/json"},
    )
    observe_redirect(coordinator, issuer_request, callback)
    assert await coordinator.next_target() == callback
    coordinator.finish()


def test_installed_redirects_preserve_responses_and_require_four_observed_one_use_hops() -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        await synthetic_login(coordinator)
        await synthetic_login(coordinator)
        assert coordinator.receipt() == {
            "redirect_navigation": NAVIGATION,
            "server_redirects": 4,
            "explicit_redirect_navigations": 4,
        }
        with pytest.raises(RuntimeError, match="redirect refused"):
            coordinator.begin()
        with pytest.raises(RuntimeError, match="redirect refused"):
            coordinator.receipt()

    asyncio.run(exercise())


def test_installed_first_failure_is_immutable_and_contains_only_fixed_values() -> None:
    diagnostics = InstalledDiagnostics()
    first = diagnostics.capture(
        RuntimeError("private state/code/cookie"), "installed_redirect_ancestry", "callback_failure"
    )
    assert first == {
        "error": "RuntimeError",
        "reason": "installed_redirect_ancestry",
        "installed_login_phase": "callback_failure",
    }
    assert (
        diagnostics.capture(
            TimeoutError("later private deadline"),
            "installed_login_deadline",
            "callback_document",
        )
        == first
    )
    assert diagnostics.capture(ValueError("cleanup private"), "unknown", None) == first
    assert "private" not in repr(diagnostics.first)
    assert "private" not in json.dumps(first)


def test_installed_unknown_exception_class_is_not_disclosed() -> None:
    class PrivateExceptionName(Exception):
        pass

    diagnostics = InstalledDiagnostics()
    assert diagnostics.capture(PrivateExceptionName("private"), "unknown", None) == {
        "error": "UnexpectedError",
        "reason": "unknown",
    }


@pytest.mark.parametrize(
    ("reason", "phase"),
    [
        ("private state/code/cookie", None),
        ("installed_redirect_ancestry private", "callback_failure"),
        ("unknown", "private state/code/cookie"),
    ],
)
def test_installed_diagnostic_capture_refuses_nonliteral_values(
    reason: str, phase: str | None
) -> None:
    diagnostics = InstalledDiagnostics()
    with pytest.raises(ValueError, match="Closed installed diagnostic"):
        diagnostics.capture(RuntimeError("private"), reason, phase)  # type: ignore[arg-type]
    assert diagnostics.first is None


def test_installed_redirect_first_rejection_cause_survives_secondary_order_failure() -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    original = object()
    headers = arm_login(coordinator, original)
    with pytest.raises(RuntimeError):
        observe_redirect(coordinator, object(), headers["location"])
    assert coordinator.failure_reason == "installed_redirect_ancestry"
    with pytest.raises(RuntimeError):
        coordinator.begin()
    assert coordinator.failure_reason == "installed_redirect_ancestry"
    assert coordinator.failed


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("net::ERR_ABORTED", "installed_redirect_aborted"),
        ("net::ERR_CERT_AUTHORITY_INVALID", "installed_redirect_certificate"),
        ("net::ERR_TIMED_OUT", "installed_redirect_timeout"),
        ("private failure with state/code/cookie", "installed_redirect_network"),
        (None, "installed_redirect_network"),
    ],
)
def test_installed_redirect_network_diagnostics_are_finite(
    failure: str | None, reason: str
) -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    original = object()
    headers = arm_login(coordinator, original)
    with pytest.raises(RuntimeError):
        coordinator.observe_failure(
            target=headers["location"],
            method="GET",
            main_frame=True,
            redirected_from=original,
            failure=failure,
        )
    assert coordinator.failure_reason == reason
    assert "private" not in coordinator.failure_reason


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source", API + "/api/v1/auth/start?extra=1"),
        ("source", API + "/api/v1/auth/callback"),
        ("method", "POST"),
        ("main_frame", False),
        ("redirected_from", object()),
        ("status", 200),
        ("status", 302),
        ("status", 307),
        ("status", True),
    ],
)
def test_installed_redirect_response_identity_is_exact(key: str, value: object) -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    arguments = {
        "source": API + "/api/v1/auth/start",
        "method": "GET",
        "main_frame": True,
        "redirected_from": None,
        "status": 303,
        "headers": login_headers(),
        key: value,
    }
    with pytest.raises(RuntimeError, match="redirect refused"):
        coordinator.arm(object(), **arguments)  # type: ignore[arg-type]
    assert coordinator.failed
    assert coordinator.failure_reason == (
        "installed_redirect_source"
        if key == "source"
        else "installed_redirect_status"
        if key == "status"
        else "installed_redirect_request_identity"
    )
    with pytest.raises(RuntimeError, match="redirect refused"):
        coordinator.receipt()


@pytest.mark.parametrize(
    "target",
    [
        "https://example.org/authorize",
        "http://127.0.0.1:4445/authorize",
        "https://127.0.0.1:4446/authorize",
        "https://user@127.0.0.1:4445/authorize",
        ISSUER + "/token",
        ISSUER + "/authorize#",
        ISSUER + "/authorize#fragment",
        ISSUER + "/authorize?state=%zz",
        ISSUER + "/authorize?state=%0A",
        ISSUER + "/authorize?state=%00",
        ISSUER + "/authorize?state=a&state=b",
        ISSUER + "/authorize?state",
        ISSUER + "/authorize?state=",
        ISSUER + "/authorize?state=" + "s" * 4096,
        ISSUER + "/authorize\n",
        "https://[",
    ],
)
def test_installed_redirect_location_refusals_latch(target: str) -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    with pytest.raises(RuntimeError, match="redirect refused"):
        coordinator.arm(
            object(),
            source=API + "/api/v1/auth/start",
            method="GET",
            main_frame=True,
            redirected_from=None,
            status=303,
            headers={**login_headers(), "location": target},
        )
    assert coordinator.failed


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("client_id", "other-client"),
        ("redirect_uri", API + "/other"),
        ("response_type", "token"),
        ("scope", "openid email"),
        ("code_challenge_method", "plain"),
        ("state", "short"),
        ("nonce", "short"),
        ("code_challenge", "short"),
        ("unapproved", "extra"),
    ],
)
def test_installed_redirect_authorization_query_is_fixed(key: str, value: str) -> None:
    headers = login_headers()
    query = dict(parse_qs(urlsplit(headers["location"]).query))
    query[key] = [value]
    headers["location"] = ISSUER + "/authorize?" + urlencode(query, doseq=True)
    coordinator = bound_redirects()
    coordinator.begin()
    with pytest.raises(RuntimeError, match="redirect refused"):
        coordinator.arm(
            object(),
            source=API + "/api/v1/auth/start",
            method="GET",
            main_frame=True,
            redirected_from=None,
            status=303,
            headers=headers,
        )
    assert coordinator.failed


@pytest.mark.parametrize(
    ("replace", "value"),
    [
        ("; Secure", ""),
        ("; HttpOnly", ""),
        ("Max-Age=300", "Max-Age=301"),
        ("Path=/", "Path=/other"),
        ("SameSite=lax", "SameSite=none"),
        ("s" * 43, "t" * 43),
        ("; Secure", "; Domain=127.0.0.1; Secure"),
        ("; Secure", "; Secure\nsecond=unknown"),
    ],
)
def test_installed_redirect_flow_cookie_is_server_exact(replace: str, value: str) -> None:
    headers = login_headers()
    headers["set-cookie"] = headers["set-cookie"].replace(replace, value)
    coordinator = bound_redirects()
    coordinator.begin()
    with pytest.raises(RuntimeError, match="redirect refused"):
        coordinator.arm(
            object(),
            source=API + "/api/v1/auth/start",
            method="GET",
            main_frame=True,
            redirected_from=None,
            status=303,
            headers=headers,
        )
    assert coordinator.failed


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("target", API + "/auth/complete?state=unobserved"),
        ("method", "POST"),
        ("main_frame", False),
        ("redirected_from", None),
        ("redirected_from", object()),
        ("failure", None),
        ("failure", "net::ERR_ABORTED"),
        ("failure", "net::ERR_CERT_AUTHORITY_INVALID"),
        ("failure", "net::ERR_TIMED_OUT"),
    ],
)
def test_installed_redirect_failure_never_recovers_other_errors(key: str, value: object) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        headers = arm_login(coordinator, original)
        arguments = {
            "target": headers["location"],
            "method": "GET",
            "main_frame": True,
            "redirected_from": original,
            "failure": "net::ERR_CONNECTION_REFUSED",
            key: value,
        }
        with pytest.raises(RuntimeError, match="redirect refused"):
            coordinator.observe_failure(**arguments)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="redirect refused"):
            await coordinator.next_target()
        assert coordinator.failed

    asyncio.run(exercise())


@pytest.mark.parametrize("failure_point", ["unarmed", "duplicate", "replay", "wrong_order"])
def test_installed_redirect_order_and_replay_latch(failure_point: str) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        target = login_headers()["location"]
        if failure_point != "unarmed":
            arm_login(coordinator, original)
        if failure_point in {"duplicate", "replay"}:
            observe_redirect(coordinator, original, target)
        if failure_point == "replay":
            assert await coordinator.next_target() == target
        with pytest.raises(RuntimeError, match="redirect refused"):
            if failure_point == "wrong_order":
                arm_login(coordinator, original)
            else:
                observe_redirect(coordinator, original, target)
        with pytest.raises(RuntimeError, match="redirect refused"):
            coordinator.finish()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "change", ["state", "code", "extra", "duplicate", "cookie", "wrong_source", "wrong_status"]
)
def test_installed_callback_redirect_remains_state_bound(change: str) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        headers = arm_login(coordinator, original)
        observe_redirect(coordinator, original, headers["location"])
        target = await coordinator.next_target()
        query = {"state": "s" * 43, "code": "c" * 32}
        if change in {"state", "code"}:
            query[change] = "wrong"
        if change == "extra":
            query["extra"] = "refuse"
        callback = API + "/auth/complete?" + urlencode(query)
        if change == "duplicate":
            callback += "&state=" + "s" * 43
        response = {"location": callback}
        if change == "cookie":
            response["set-cookie"] = "unexpected=value"
        with pytest.raises(RuntimeError, match="redirect refused"):
            coordinator.arm(
                object(),
                source=API + "/api/v1/auth/start" if change == "wrong_source" else target,
                method="GET",
                main_frame=True,
                redirected_from=None,
                status=302 if change == "wrong_status" else 303,
                headers=response,
            )
        assert coordinator.failed

    asyncio.run(exercise())


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
    assert "if not redirects.active or not incoming.is_navigation_request():" in guest
    assert guest.count('name="Retry connection", exact=True') == 2
    login = guest[guest.index("async def login()") : guest.index('checkpoint("assets_session")')]
    assert login.count("asyncio.timeout(10)") == 1
    assert login.index('name="Retry connection"') < login.index("redirects.begin()")
    assert 'status=response["status"], headers=response["headers"], body=bytes(output)' in guest
    assert guest.index("observer.arm(") < guest.index("await route.fulfill(")
    assert login.index("redirects.finish()") < login.index("login_phase = None")
    assert "finally:" not in login
    assert "type(error) is TimeoutError" in guest
    assert 'isinstance(error, Error) and route.request.failure == "net::ERR_ABORTED"' in guest
    assert '"Installed browser journey failed: " + fixed["error"]' in guest
    assert "type(error).__name__" not in guest
    assert 'name="no contact", exact=True' in guest
    assert json.loads(json.dumps(ASSETS)) == ASSETS


def test_installed_positive_work_lease_is_separate_from_browser_session_expiry() -> None:
    import ast

    from emailmonitor.runtime.worker import ServiceRuntimeConfig

    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/test_installed_operator_acceptance.py").read_text()
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ServiceRuntimeConfig"
    ]
    assert len(calls) == 1
    leases = [keyword.value for keyword in calls[0].keywords if keyword.arg == "lease_seconds"]
    assert len(leases) == 1
    expected = ast.parse('30 if kind == "worker" else 5', mode="eval").body
    assert ast.dump(leases[0]) == ast.dump(expected)
    assert ServiceRuntimeConfig.model_fields["lease_seconds"].default == 30
    assert "expires_at=clock_timestamp()+interval '500 milliseconds'" in source
    assert "AND revoked_at IS NULL AND expires_at<=clock_timestamp()" in source
    assert source.index("expiry_observed = True") < source.index("release.set()")
    assert "empty-process restart, not a crash/lease recovery claim" in source


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


@pytest.mark.parametrize("primary_exists", [False, True])
def test_installed_api_client_closes_before_process_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary_exists: bool
) -> None:
    import signal
    from unittest.mock import MagicMock

    import test_installed_operator_acceptance as harness

    events: list[str] = []
    running = MagicMock()
    running.poll.return_value = None
    running.wait.return_value = -signal.SIGTERM
    running.terminate.side_effect = lambda: events.append("terminate")
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.side_effect = lambda *_: events.append("client-close")
    monkeypatch.setattr(
        "test_installed_operator_acceptance.subprocess.Popen", MagicMock(return_value=running)
    )
    monkeypatch.setattr(
        "test_installed_operator_acceptance.httpx.Client", MagicMock(return_value=client)
    )
    primary = ValueError("original-task-failure")
    context = ssl.create_default_context()
    if primary_exists:
        with pytest.raises(ValueError) as caught:
            with harness.api_process_client(tmp_path, tmp_path / "owned.json", context):
                raise primary
        assert caught.value is primary
    else:
        with harness.api_process_client(tmp_path, tmp_path / "owned.json", context):
            pass
    assert events == ["client-close", "terminate"]
    running.wait.assert_called_once_with(timeout=5)
    running.kill.assert_not_called()


def test_installed_api_client_tls_shutdown_uses_original_five_second_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinned Uvicorn connection drain regression, without SQL or service readiness claims."""
    import signal
    import socket
    import sys
    import time

    import test_installed_operator_acceptance as harness

    cert, key = certificate(tmp_path)
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    # Use the real pinned server and TLS transport; no production configuration,
    # signal handler, shutdown setting, or certificate verification is replaced.
    code = (
        "import uvicorn\n"
        "from fastapi import FastAPI\n"
        "app=FastAPI()\n"
        "@app.get('/readyz')\n"
        "def ready(): return {'transport_probe':True}\n"
        f"uvicorn.run(app,host='127.0.0.1',port={port},"
        f"ssl_certfile={str(cert)!r},ssl_keyfile={str(key)!r},"
        "access_log=False,log_level='critical')\n"
    )
    monkeypatch.setattr(harness, "command", lambda *_: [sys.executable, "-I", "-B", "-c", code])
    with harness.api_process_client(
        tmp_path, tmp_path / "unused.json", ssl.create_default_context(cafile=str(cert))
    ) as (running, client):
        deadline = time.monotonic() + 5
        while True:
            assert running.poll() is None
            try:
                response = client.get(f"https://127.0.0.1:{port}/readyz")
                assert response.status_code == 200
                assert response.json() == {"transport_probe": True}
                break
            except httpx.ConnectError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        assert not client.is_closed
    assert client.is_closed
    assert running.returncode == -signal.SIGTERM
