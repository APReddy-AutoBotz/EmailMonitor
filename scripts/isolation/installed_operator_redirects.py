"""Two synthetic login redirects, never general failed-navigation recovery.

Pinned Chromium bypasses Playwright routing for a redirected request. The guest
receives the real 303, observes the exact failed loopback redirect, then navigates
its already-validated target once so the new request enters the HTTPS relay.
"""

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import TYPE_CHECKING, Any, NoReturn, get_args
from urllib.parse import parse_qsl, urlsplit

from operator_ui_protocol import (
    ERRORS,
    InstalledCallbackDelivery,
    InstalledLoginPhase,
    InstalledReason,
    failure_reason,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, CDPSession, Frame, Page

ERROR_DOCUMENT = "chrome-error://chromewebdata/"

NAVIGATION = "observed_303_failed_target_explicit_navigation"
FLOW_COOKIE = "__Host-emailmonitor_login"


@dataclass(frozen=True)
class PendingRedirect:
    original: object
    target: str
    sequence: int


@dataclass(frozen=True)
class FixedFailure:
    error: str
    reason: str
    phase: InstalledLoginPhase | None


class CallbackDeliveryTrace:
    """Observe one request per login generation; never authorize or emit a URL."""

    def __init__(self) -> None:
        self.generation = 0
        self.request: object | None = None
        self.value: InstalledCallbackDelivery = "not_requested"

    def reset(self) -> int:
        self.generation += 1
        self.request = None
        self.value = "not_requested"
        return self.generation

    def observe(self, generation: int, request: object, step: InstalledCallbackDelivery) -> None:
        steps = get_args(InstalledCallbackDelivery)
        if generation != self.generation or step not in steps:
            return
        if self.request is None:
            if step != "request_received":
                return
            self.request = request
        if request is self.request and steps.index(step) > steps.index(self.value):
            self.value = step


class InstalledDiagnostics:
    """Retain only the first finite diagnostic; never retain exception text."""

    def __init__(self) -> None:
        self.first: FixedFailure | None = None

    def capture(
        self, error: BaseException, reason: str, phase: InstalledLoginPhase | None
    ) -> dict[str, str]:
        if reason not in {"unknown", "keyboard_focus", *get_args(InstalledReason)} or (
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


def installed_relay_reason(error: BaseException) -> InstalledReason:
    """Classify only exact authored guards; no exception text enters diagnostics."""
    known = failure_reason(error)
    if known == "rpc_request_capacity":
        return "installed_relay_request_capacity"
    if known == "rpc_admission_capacity":
        return "installed_relay_admission_capacity"
    if (
        type(error) is RuntimeError
        and len(error.args) == 1
        and type(error.args[0]) is str
        and error.args[0] == "UI diagnostic request too large"
    ):
        return "installed_relay_request_size"
    return "installed_route_relay"


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
        self._frame = ""
        self._loaders: set[str] = set()
        self._loader: str | None = None
        self._cdp_loaded = False
        self._public_commit = False
        self._public_loaded = False
        self._event = asyncio.Event()

    def bind_frame(self, frame: str) -> None:
        if self._frame or self.active or not self._identifier(frame):
            self._reject("installed_redirect_order_bind")
        self._frame = frame

    @staticmethod
    def _identifier(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value))

    def _ready(self) -> bool:
        return (
            self._observed
            and self._loader is not None
            and self._cdp_loaded
            and self._public_commit
            and self._public_loaded
        )

    def _wake(self) -> None:
        if self._ready():
            self._event.set()

    def observe_commit(self, *, frame: str, loader: str, url: str, target: str) -> None:
        """Read-only CDP identity gate; values never enter a receipt or log."""
        pending = self._pending
        if pending is None:
            if self.active and url == ERROR_DOCUMENT:
                self._reject("installed_redirect_order_commit")
            return
        if self.failed or frame != self._frame or url != ERROR_DOCUMENT or target != pending.target:
            self._reject("installed_redirect_failure_identity")
        if self._loader is not None or loader in self._loaders or not self._identifier(loader):
            self._reject("installed_redirect_order_commit")
        if len(self._loaders) >= 4:
            self._reject("installed_redirect_order_commit")
        self._loaders.add(loader)
        self._loader = loader
        self._wake()

    def observe_lifecycle(self, *, frame: str, loader: str, name: str) -> None:
        if self._pending is None or name != "DOMContentLoaded":
            return
        # Unrelated/early lifecycle events cannot satisfy the owned commit.
        if loader != self._loader:
            if loader in self._loaders:
                self._reject("installed_redirect_order_lifecycle")
            return
        if self.failed or frame != self._frame or self._cdp_loaded:
            self._reject("installed_redirect_order_lifecycle")
        self._cdp_loaded = True
        self._wake()

    def observe_public_commit(self, *, sequence: int, main_frame: bool, url: str) -> None:
        pending = self._pending
        if self.failed or pending is None or pending.sequence != sequence:
            self._reject("installed_redirect_order_public_commit")
        if not main_frame or url != ERROR_DOCUMENT or self._public_commit:
            self._reject("installed_redirect_failure_identity")
        self._public_commit = True
        self._wake()

    def observe_public_loaded(self, *, sequence: int) -> None:
        pending = self._pending
        if self.failed or pending is None or pending.sequence != sequence or self._public_loaded:
            self._reject("installed_redirect_order_public_load")
        if not self._public_commit:
            return
        self._public_loaded = True
        self._wake()

    def invalidate(self) -> None:
        self.failed = True
        self._event.set()

    def _reject(self, reason: InstalledReason = "installed_redirect_order") -> NoReturn:
        if self.failure_reason is None:
            self.failure_reason = reason
        self.invalidate()
        raise RuntimeError("Synthetic login redirect refused") from None

    def begin(self) -> None:
        if self.failed or self.active or self.logins >= 2 or self._pending is not None:
            self._reject("installed_redirect_order_begin")
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
        if (
            self.failed
            or not self.active
            or not self._frame
            or self._pending is not None
            or self._phase not in {0, 1}
        ):
            self._reject("installed_redirect_order_arm")
        if source != self._source:
            self._reject("installed_redirect_source")
        if method != "GET" or not main_frame or redirected_from is not None:
            self._reject("installed_redirect_request_identity")
        if type(status) is not int or status != 303:
            self._reject("installed_redirect_status")
        self._pending = PendingRedirect(original, self._target(headers), self.redirects + 1)
        self.redirects += 1
        self._loader = None
        self._cdp_loaded = False
        self._public_commit = False
        self._public_loaded = False
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
            reason: InstalledReason = (
                "installed_redirect_failure_latched"
                if self.failed
                else "installed_redirect_failure_inactive"
                if not self.active
                else "installed_redirect_failure_unarmed"
                if pending is None
                else "installed_redirect_failure_duplicate"
            )
            self._reject(reason)
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
        self._wake()

    async def next_target(self) -> str:
        # The caller owns one unchanged ten-second budget for the entire login.
        await self._event.wait()
        if self.failed or not self.active or self._pending is None or not self._ready():
            self._reject("installed_redirect_order_next")
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
            self._reject("installed_redirect_order_finish")
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
            self._reject("installed_redirect_order_receipt")
        return {
            "redirect_navigation": NAVIGATION,
            "server_redirects": 4,
            "explicit_redirect_navigations": 4,
        }


class ErrorDocumentObserver:
    """Own only Page observation; never navigate, intercept, or change network state."""

    def __init__(
        self,
        page: "Page",
        session: "CDPSession",
        redirects: LoginRedirects,
        capture: Callable[[RuntimeError], None],
    ) -> None:
        self.page, self.session, self.redirects = page, session, redirects
        self.capture = capture
        self.listeners: list[tuple[Any, str, Callable[..., None]]] = []
        self.public: list[tuple[Any, str, Callable[..., None]]] = []
        self.closed = False

    def _call(self, action: Callable[[], None]) -> None:
        try:
            action()
        except RuntimeError as error:
            self.capture(error)

    def _listen(
        self, owner: Any, name: str, callback: Callable[..., None], *, public: bool = False
    ) -> None:
        # Record ownership before registration, so partial registration rolls back.
        (self.public if public else self.listeners).append((owner, name, callback))
        owner.on(name, callback)

    def install(self) -> None:
        def committed(event: dict[str, Any]) -> None:
            frame = event["frame"]
            # Child-frame traffic cannot supply the main frame's barrier.
            if frame.get("parentId") and frame.get("url") != ERROR_DOCUMENT:
                return
            self._call(
                lambda: self.redirects.observe_commit(
                    frame=frame.get("id", ""),
                    loader=frame.get("loaderId", ""),
                    url=frame.get("url", ""),
                    target=frame.get("unreachableUrl", ""),
                )
            )

        def lifecycle(event: dict[str, Any]) -> None:
            self._call(
                lambda: self.redirects.observe_lifecycle(
                    frame=event.get("frameId", ""),
                    loader=event.get("loaderId", ""),
                    name=event.get("name", ""),
                )
            )

        self._listen(self.session, "Page.frameNavigated", committed)
        self._listen(self.session, "Page.lifecycleEvent", lifecycle)

    def arm(self, original: object, **arguments: Any) -> None:
        if self.closed or self.public:
            self.redirects._reject("installed_redirect_order_observer")
        sequence = self.redirects.redirects + 1

        def committed(frame: "Frame") -> None:
            self._call(
                lambda: self.redirects.observe_public_commit(
                    sequence=sequence,
                    main_frame=frame == self.page.main_frame,
                    url=frame.url,
                )
            )

        def loaded() -> None:
            self._call(lambda: self.redirects.observe_public_loaded(sequence=sequence))

        # Both streams are observed before arming and fulfilling the real 303.
        self._listen(self.page, "framenavigated", committed, public=True)
        self._listen(self.page, "domcontentloaded", loaded, public=True)
        self.redirects.arm(original, **arguments)

    def _remove(self, listeners: list[tuple[Any, str, Callable[..., None]]]) -> None:
        errors = []
        for owner, name, callback in listeners:
            try:
                owner.remove_listener(name, callback)
            except BaseException as error:
                errors.append(error)
        listeners.clear()
        if errors:
            self.redirects.invalidate()
            raise RuntimeError("Owned observer listener cleanup failed") from None

    async def next_target(self) -> str:
        target = await self.redirects.next_target()
        self._remove(self.public)
        return target

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        errors: list[BaseException] = []
        if self.public:
            self.redirects.invalidate()
            errors.append(RuntimeError("Owned observation closed while pending"))
        for listeners in (self.public, self.listeners):
            try:
                self._remove(listeners)
            except BaseException as error:
                errors.append(error)
        try:
            async with asyncio.timeout(5):
                await self.session.detach()
        except BaseException as error:
            errors.append(error)
        if errors:
            self.redirects.invalidate()
            raise RuntimeError("Owned observer cleanup failed") from None


@asynccontextmanager
async def observe_error_documents(
    context: "BrowserContext",
    page: "Page",
    redirects: LoginRedirects,
    capture: Callable[[RuntimeError], None],
) -> AsyncIterator[ErrorDocumentObserver]:
    observer: ErrorDocumentObserver | None = None
    primary: BaseException | None = None
    try:
        async with asyncio.timeout(10):
            session = await context.new_cdp_session(page)
            observer = ErrorDocumentObserver(page, session, redirects, capture)
            observer.install()
            await session.send("Page.enable")
            tree = await session.send("Page.getFrameTree")
            redirects.bind_frame(tree["frameTree"]["frame"]["id"])
            await session.send("Page.setLifecycleEventsEnabled", {"enabled": True})
        yield observer
    except BaseException as error:
        primary = error
        redirects.invalidate()
        raise
    finally:
        if observer is not None:
            try:
                await observer.close()
            except BaseException:
                if primary is None:
                    raise
                primary.add_note("Owned observer cleanup also failed")
