"""Two synthetic login redirects, never general failed-navigation recovery.

Pinned Chromium bypasses Playwright routing for a redirected request. The guest
receives the real 303, observes the exact failed loopback redirect, then navigates
its already-validated target once so the new request enters the HTTPS relay.
"""

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import NoReturn, get_args
from urllib.parse import parse_qsl, urlsplit

from operator_ui_protocol import ERRORS, InstalledLoginPhase, InstalledReason

NAVIGATION = "observed_303_failed_target_explicit_navigation"
FLOW_COOKIE = "__Host-emailmonitor_login"


@dataclass(frozen=True)
class PendingRedirect:
    original: object
    target: str


@dataclass(frozen=True)
class FixedFailure:
    error: str
    reason: str
    phase: InstalledLoginPhase | None


class InstalledDiagnostics:
    """Retain only the first finite diagnostic; never retain exception text."""

    def __init__(self) -> None:
        self.first: FixedFailure | None = None

    def capture(
        self, error: BaseException, reason: str, phase: InstalledLoginPhase | None
    ) -> dict[str, str]:
        if reason not in {"unknown", *get_args(InstalledReason)} or (
            phase is not None and phase not in get_args(InstalledLoginPhase)
        ):
            raise ValueError("Closed installed diagnostic required")
        if self.first is None:
            name = type(error).__name__
            self.first = FixedFailure(name if name in ERRORS else "UnexpectedError", reason, phase)
        result = {"error": self.first.error, "reason": self.first.reason}
        if self.first.phase is not None:
            result["installed_login_phase"] = self.first.phase
        return result


class LoginRedirects:
    """Fail-closed, one-use coordinator for exactly two two-hop logins."""

    def __init__(self, api: str, issuer: str) -> None:
        for origin in (api, issuer):
            if not re.fullmatch(r"https://127\.0\.0\.1:[1-9][0-9]{0,4}", origin):
                raise RuntimeError("Exact synthetic redirect origin required")
            if not 0 < (urlsplit(origin).port or 0) < 65536:
                raise RuntimeError("Exact synthetic redirect port required")
        if api == issuer:
            raise RuntimeError("Distinct synthetic redirect origins required")
        self.api = api
        self.issuer = issuer
        self.active = False
        self.failed = False
        self.failure_reason: InstalledReason | None = None
        self.logins = 0
        self.redirects = 0
        self.navigations = 0
        self._phase = 0
        self._source = ""
        self._state = ""
        self._pending: PendingRedirect | None = None
        self._observed = False
        self._event = asyncio.Event()

    def _reject(self, reason: InstalledReason = "installed_redirect_order") -> NoReturn:
        if self.failure_reason is None:
            self.failure_reason = reason
        self.failed = True
        self._event.set()
        raise RuntimeError("Synthetic login redirect refused") from None

    def begin(self) -> None:
        if self.failed or self.active or self.logins >= 2 or self._pending is not None:
            self._reject()
        self.active = True
        self._phase = 0
        self._source = self.api + "/api/v1/auth/start"
        self._state = ""
        self._event.clear()

    def _query(self, target: str, origin: str, path: str) -> dict[str, str]:
        if (
            not 1 <= len(target) <= 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in target)
            or re.search(r"%(?![0-9a-fA-F]{2})", target)
        ):
            self._reject("installed_redirect_location")
        try:
            parsed = urlsplit(target)
        except ValueError:
            self._reject("installed_redirect_location")
        if (
            f"{parsed.scheme}://{parsed.netloc}" != origin
            or parsed.path != path
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or "#" in target
        ):
            self._reject("installed_redirect_location")
        try:
            pairs = parse_qsl(
                parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8
            )
        except ValueError:
            self._reject("installed_redirect_query")
        if (
            len(pairs) != len(dict(pairs))
            or any(not value for _, value in pairs)
            or any(
                ord(char) < 33 or ord(char) > 126
                for pair in pairs
                for item in pair
                for char in item
            )
        ):
            self._reject("installed_redirect_query")
        return dict(pairs)

    def _target(self, headers: Mapping[str, str]) -> str:
        if any(key != key.lower() for key in headers) or "location" not in headers:
            self._reject("installed_redirect_location")
        target = headers["location"]
        if self._phase == 0:
            query = self._query(target, self.issuer, "/authorize")
            fixed = {
                "client_id": "installed-operator-test",
                "redirect_uri": self.api + "/auth/complete",
                "response_type": "code",
                "scope": "openid",
                "code_challenge_method": "S256",
            }
            if set(query) != set(fixed) | {"state", "nonce", "code_challenge"} or any(
                query.get(key) != value for key, value in fixed.items()
            ):
                self._reject("installed_redirect_authorization")
            if any(
                not re.fullmatch(r"[A-Za-z0-9_-]{43}", query[key])
                for key in ("state", "nonce", "code_challenge")
            ):
                self._reject("installed_redirect_authorization")
            raw_cookie = headers.get("set-cookie", "")
            if not 1 <= len(raw_cookie) <= 4096 or any(
                ord(char) < 32 or ord(char) > 126 for char in raw_cookie
            ):
                self._reject("installed_redirect_cookie")
            cookie = SimpleCookie()
            try:
                cookie.load(raw_cookie)
            except CookieError:
                self._reject("installed_redirect_cookie")
            if set(cookie) != {FLOW_COOKIE}:
                self._reject("installed_redirect_cookie")
            flow = cookie[FLOW_COOKIE]
            if (
                flow.value != query["state"]
                or flow["path"] != "/"
                or flow["domain"]
                or flow["max-age"] != "300"
                or flow["samesite"].lower() != "lax"
                or flow["secure"] is not True
                or flow["httponly"] is not True
            ):
                self._reject("installed_redirect_cookie")
            self._state = query["state"]
        else:
            query = self._query(target, self.api, "/auth/complete")
            if set(query) != {"state", "code"}:
                self._reject("installed_redirect_callback_query")
            if query.get("state") != self._state:
                self._reject("installed_redirect_state")
            if not re.fullmatch(r"[A-Za-z0-9_-]{32}", query.get("code", "")):
                self._reject("installed_redirect_callback_query")
            if "set-cookie" in headers:
                self._reject("installed_redirect_cookie")
        return target

    def arm(
        self,
        original: object,
        *,
        source: str,
        method: str,
        main_frame: bool,
        redirected_from: object | None,
        status: int,
        headers: Mapping[str, str],
    ) -> None:
        """Call before fulfilling the unchanged real response into Chromium."""
        if self.failed or not self.active or self._pending is not None or self._phase not in {0, 1}:
            self._reject()
        if source != self._source:
            self._reject("installed_redirect_source")
        if method != "GET" or not main_frame or redirected_from is not None:
            self._reject("installed_redirect_request_identity")
        if type(status) is not int or status != 303:
            self._reject("installed_redirect_status")
        self._pending = PendingRedirect(original, self._target(headers))
        self.redirects += 1
        self._observed = False
        self._event.clear()

    def observe_failure(
        self,
        *,
        target: str,
        method: str,
        main_frame: bool,
        redirected_from: object | None,
        failure: str | None,
    ) -> None:
        pending = self._pending
        if self.failed or not self.active or pending is None or self._observed:
            self._reject()
        if target != pending.target or method != "GET" or not main_frame:
            self._reject("installed_redirect_failure_identity")
        if redirected_from is not pending.original:
            self._reject("installed_redirect_ancestry")
        if failure != "net::ERR_CONNECTION_REFUSED":
            if failure == "net::ERR_ABORTED":
                self._reject("installed_redirect_aborted")
            if failure == "net::ERR_CERT_AUTHORITY_INVALID":
                self._reject("installed_redirect_certificate")
            if failure == "net::ERR_TIMED_OUT":
                self._reject("installed_redirect_timeout")
            self._reject("installed_redirect_network")
        self._observed = True
        self._event.set()

    async def next_target(self) -> str:
        # The caller owns one unchanged ten-second budget for the entire login.
        await self._event.wait()
        if self.failed or not self.active or self._pending is None or not self._observed:
            self._reject()
        assert self._pending is not None
        target = self._pending.target
        self._pending = None
        self._phase += 1
        self._source = target
        self.navigations += 1
        self._observed = False
        self._event.clear()
        return target

    def finish(self) -> None:
        if self.failed or not self.active or self._phase != 2 or self._pending is not None:
            self._reject()
        self.active = False
        self.logins += 1

    def receipt(self) -> dict[str, str | int]:
        if (
            self.failed
            or self.active
            or self.logins != 2
            or self.redirects != 4
            or self.navigations != 4
        ):
            self._reject()
        return {
            "redirect_navigation": NAVIGATION,
            "server_redirects": 4,
            "explicit_redirect_navigations": 4,
        }
