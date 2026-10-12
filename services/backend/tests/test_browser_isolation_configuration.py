"""Static configuration integrity only; no sandbox/browser execution claim."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_only_approved_namespace_and_chroot_syscalls_are_added_to_pinned_current_profile() -> None:
    directory = ROOT / "scripts/isolation"
    raw = (directory / "seccomp-default.json").read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "6416b47770785a41ac59073cdc77d9fe98517df2799dc83ef207e622de3053f6"
    )
    base = json.loads(raw)
    derived = json.loads((directory / "seccomp-browser.json").read_text())
    assert derived["syscalls"][-1] == {
        "names": ["chroot"],
        "action": "SCMP_ACT_ALLOW",
        "comment": (
            "Modified for separately approved synthetic browser CI: "
            "allow chroot for namespace filesystem isolation."
        ),
    }
    derived["syscalls"].pop()
    assert derived["syscalls"][-1] == {
        "names": ["clone", "setns", "unshare"],
        "action": "SCMP_ACT_ALLOW",
        "comment": "Modified for approved synthetic browser CI: allow clone, setns, unshare.",
    }
    derived["syscalls"].pop()
    assert derived == base
    assert any(rule["names"] == ["clone3"] and rule["errnoRet"] == 38 for rule in base["syscalls"])
    assert not any(
        "io_uring_setup" in rule["names"] and rule["action"] == "SCMP_ACT_ALLOW"
        for rule in base["syscalls"]
    )
    assert (directory / "licenses/moby-profiles-LICENSE").is_file()


def test_browser_launch_is_explicitly_sandboxed_and_network_mediation_is_present() -> None:
    guest = (ROOT / "scripts/isolation/browser_acceptance.py").read_text()
    assert "chromium_sandbox=True" in guest and 'service_workers="block"' in guest
    assert 'context.route("**/*", route_request)' in guest
    assert 'context.route_web_socket("**/*", websocket)' in guest
    assert "accept_downloads=False" in guest and "item.cancel()" in guest
    assert "chrome://sandbox" in guest and '"--no-sandbox"' in guest
    assert 'interfaces != ["lo"]' in guest
    assert '"192.0.2.1"' in guest and '"2001:db8::1"' in guest
    assert "169.254.169.254" not in guest
    assert "os.environ.get(name) != expected" in guest
    for directory in ("/tmp/browser-home", "/tmp/browser-config", "/tmp/browser-cache"):
        assert directory in guest


def test_approved_browser_container_has_no_host_or_service_access() -> None:
    host = (ROOT / "scripts/isolation/run_browser_acceptance.py").read_text()
    for required in (
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--security-opt=seccomp=",
        "--read-only",
        "--user=1000:1000",
        "--memory=512m",
        "--memory-swap=512m",
        "--pids-limit=128",
        "--shm-size=128m",
        "--env=HOME=/tmp/browser-home",
        "--env=XDG_CONFIG_HOME=/tmp/browser-config",
        "--env=CHROME_CONFIG_HOME=/tmp/browser-config",
        "--env=XDG_CACHE_HOME=/tmp/browser-cache",
    ):
        assert required in host
    for forbidden in (
        "--privileged",
        "--cap-add",
        "--network=host",
        "--ipc=host",
        "seccomp=unconfined",
        "docker.sock",
        "--mount",
        "--volume",
        "sysctl",
        "iptables",
    ):
        assert forbidden not in host
    assert "8192" in host and "262144" in host and "16384" in host
    assert 'errors.decode(errors="replace")' in host and "[:1000]" not in host
    assert "process.kill()" in host and 'docker("rm", "--force", identifier)' in host
    workflow = (ROOT / ".github/workflows/browser-isolation.yml").read_text()
    assert "contents: read" in workflow and "persist-credentials: false" in workflow
    assert "pull_request_target" not in workflow and "secrets." not in workflow


def test_immutable_browser_runtime_and_preserved_wheel_notices() -> None:
    import importlib.metadata

    inventory = json.loads((ROOT / "reports/runtime-inventory.json").read_text())
    image = inventory["playwright_browser"]["image"]
    assert (
        "FROM --platform=linux/amd64 " + image + "\n"
        in (ROOT / "scripts/isolation/Dockerfile.browser").read_text()
    )
    distribution = importlib.metadata.distribution("playwright")
    assert distribution.version == "1.63.0"
    for relative in (
        "playwright/driver/LICENSE",
        "playwright/driver/package/LICENSE",
        "playwright/driver/package/NOTICE",
        "playwright/driver/package/ThirdPartyNotices.txt",
        "playwright/driver/package/lib/utilsBundle.js.LICENSE",
        "playwright/driver/package/lib/serverRegistry.js.LICENSE",
    ):
        assert Path(str(distribution.locate_file(relative))).is_file()


def test_pinned_service_worker_block_checks_absence_not_rejection_only() -> None:
    import importlib.metadata

    distribution = importlib.metadata.distribution("playwright")
    driver = Path(str(distribution.locate_file("playwright/driver/package/lib/coreBundle.js")))
    assert "navigator.serviceWorker.register = async () => { console.warn(" in driver.read_text()
    host = (ROOT / "scripts/isolation/run_browser_acceptance.py").read_text()
    guest = (ROOT / "scripts/isolation/browser_acceptance.py").read_text()
    assert "state.worker_blocked=!reg" in host and "state.worker_blocked=true" in host
    assert 'endswith("/worker.js")' in host
    assert "getRegistrations().then(r=>r.length)" in guest
    assert 'registrations != 0 or not state["worker_blocked"]' in guest
    assert "context.service_workers" in guest


SANDBOX_TABLE = (
    "Layer 1 Sandbox\tNamespace\nPID namespaces\tYes\nNetwork namespaces\tYes\n"
    "Seccomp-BPF sandbox\tYes\nSeccomp-BPF sandbox supports TSYNC\tYes\n"
    "Ptrace Protection with Yama LSM (Broker)\tYes\n"
    "Ptrace Protection with Yama LSM (Non-broker)\tNo"
)


def check_sandbox_text(text: str, evaluation: str) -> dict[str, bool]:
    import runpy
    from collections.abc import Callable
    from typing import cast

    namespace = runpy.run_path(str(ROOT / "scripts/isolation/browser_acceptance.py"))
    checker = cast(Callable[[str, str], dict[str, bool]], namespace["sandbox_status"])
    return checker(text, evaluation)


def test_pinned_sandbox_table_and_own_evaluation_are_positive() -> None:
    assert all(check_sandbox_text(SANDBOX_TABLE, "You are adequately sandboxed.").values())


def test_pinned_sandbox_table_tolerates_only_cell_surrounding_whitespace() -> None:
    table = "\n".join(" " + line.replace("\t", " \t ") + " " for line in SANDBOX_TABLE.splitlines())
    assert all(check_sandbox_text(table, " You are adequately sandboxed. ").values())


def test_sandbox_parser_rejects_missing_false_duplicate_and_substring_rows() -> None:
    import pytest

    for table in (
        "",
        SANDBOX_TABLE.split("\n", 1)[1],
        SANDBOX_TABLE.replace("\tNamespace", "\tSUID"),
        SANDBOX_TABLE.replace("\tNamespace", "\tNone"),
        SANDBOX_TABLE.replace("sandbox\tYes", "sandbox\tNo"),
        SANDBOX_TABLE.replace("PID namespaces\tYes", "PID namespaces\tNo"),
        SANDBOX_TABLE.replace("Network namespaces\tYes", "Network namespaces\tNo"),
        SANDBOX_TABLE + "\nLayer 1 Sandbox\tNamespace",
        SANDBOX_TABLE.replace("\tNamespace", "\tNamespace disabled"),
        SANDBOX_TABLE.replace("Layer 1 Sandbox", "Namespace sandbox"),
        SANDBOX_TABLE + "\nUnknown row\tYes",
        SANDBOX_TABLE.replace("Layer 1 Sandbox\tNamespace", "Layer 1 Sandbox Namespace"),
    ):
        with pytest.raises(RuntimeError):
            check_sandbox_text(table, "You are adequately sandboxed.")


def test_sandbox_parser_requires_own_affirmative_evaluation() -> None:
    import pytest

    for evaluation in ("", "You are NOT adequately sandboxed.", "You are adequately sandboxed. No"):
        with pytest.raises(RuntimeError):
            check_sandbox_text(SANDBOX_TABLE, evaluation)


def test_sandbox_failure_evidence_is_bounded_and_preserves_negative_status() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="NOT adequately") as error:
        check_sandbox_text("x" * 10000, "You are NOT adequately sandboxed.")
    assert len(str(error.value)) < 4500


def classify_network_text(text: str) -> str:
    import runpy
    from collections.abc import Callable
    from typing import cast

    namespace = runpy.run_path(str(ROOT / "scripts/isolation/browser_acceptance.py"))
    classifier = cast(Callable[[str], str], namespace["classify_browser_network_error"])
    return classifier(text)


def test_browser_network_error_accepts_only_exact_pinned_navigation_denials() -> None:
    for code in ("ERR_ADDRESS_UNREACHABLE", "ERR_INTERNET_DISCONNECTED"):
        assert (
            classify_network_text(
                f"Page.goto: net::{code} at http://192.0.2.1:443/\nCall log:\n - navigating"
            )
            == code
        )


def test_browser_network_error_rejects_timeout_unknown_success_and_other_destinations() -> None:
    import pytest

    for message in (
        "Page.goto: Timeout 5000ms exceeded.",
        "Page.goto: net::ERR_TIMED_OUT at http://192.0.2.1:443/",
        "Page.goto: net::ERR_FAILED at http://192.0.2.1:443/",
        "Page.goto: net::ERR_NETWORK_UNREACHABLE at http://192.0.2.1:443/",
        "Page.goto: HTTP 200 at http://192.0.2.1:443/",
        "Page.goto: net::ERR_INTERNET_DISCONNECTED at https://denied.fixture.example/",
        "Unexpected error mentioning ERR_INTERNET_DISCONNECTED",
        "Page.goto: net::ERR_INTERNET_DISCONNECTED at http://192.0.2.1:443/evil",
        "",
    ):
        with pytest.raises(RuntimeError):
            classify_network_text(message)


def test_browser_denial_keeps_independent_kernel_interface_evidence_and_success_refusal() -> None:
    guest = (ROOT / "scripts/isolation/browser_acceptance.py").read_text()
    assert "result != errno.ENETUNREACH" in guest and 'interfaces != ["lo"]' in guest
    assert 'raise RuntimeError("Browser escaped network-none namespace")' in guest
    assert "set_offline" not in guest and "offline=True" not in guest


def format_timeout_context(stderr: bytes, last_request: dict[str, str]) -> str:
    import runpy
    from collections.abc import Callable
    from typing import cast

    namespace = runpy.run_path(str(ROOT / "scripts/isolation/run_browser_acceptance.py"))
    formatter = cast(
        Callable[[int, int, int, dict[str, str], bytes], str], namespace["timeout_evidence"]
    )
    return formatter(4, 2, 2, last_request, stderr)


def test_timeout_context_records_counters_last_request_and_bounded_stage_tail() -> None:
    message = format_timeout_context(
        b"x" * 10000 + b"synthetic-browser-stage:click_start",
        {"url": "https://denied.fixture.example/image", "resource": "image", "method": "GET"},
    )
    payload = json.loads(message.split(": ", 1)[1])
    assert payload["requests"] == 4 and payload["accepted"] == 2 and payload["denied"] == 2
    assert payload["guest_stderr"].endswith("synthetic-browser-stage:click_start")
    assert len(payload["guest_stderr"]) <= 2048
    assert payload["last_request"]["resource"] == "image"


def test_timeout_context_never_increases_deadline_or_unbounds_guest_output() -> None:
    message = format_timeout_context(b"\x00" * 10000, {"url": "x" * 10000, "resource": "x" * 10000})
    assert len(message) <= 16384
    host = (ROOT / "scripts/isolation/run_browser_acceptance.py").read_text()
    guest = (ROOT / "scripts/isolation/browser_acceptance.py").read_text()
    assert "deadline = time.monotonic() + 60" in host and "len(errors) > 16384" in host
    assert "synthetic-browser-stage:" in guest and "file=sys.stderr, flush=True" in guest


def async_guest_namespace() -> dict[str, object]:
    import runpy

    return runpy.run_path(str(ROOT / "scripts/isolation/browser_acceptance.py"))


def test_async_fixture_exchanges_are_serialized_and_numbered() -> None:
    import asyncio
    import io
    from typing import Any, cast

    channel_type = cast(Any, async_guest_namespace()["FixtureChannel"])
    writer = io.StringIO()
    channel = channel_type(io.BytesIO(b'{"status":"denied"}\n' * 3), writer)

    async def exercise() -> None:
        replies = await asyncio.gather(
            *(channel.request("https://denied.fixture.example/", "GET", "image") for _ in range(3))
        )
        assert all(reply == {"status": "denied"} for reply in replies)

    asyncio.run(exercise())
    assert [json.loads(line)["identifier"] for line in writer.getvalue().splitlines()] == [1, 2, 3]
    assert channel.requests == 3


def test_async_fixture_channel_preserves_request_reply_caps_and_failure_refusal() -> None:
    import asyncio
    import io
    from typing import Any, cast

    import pytest

    channel_type = cast(Any, async_guest_namespace()["FixtureChannel"])

    async def exercise() -> None:
        channel = channel_type(io.BytesIO(b'{"status":"denied"}\n' * 64), io.StringIO())
        for _ in range(64):
            await channel.request("https://denied.fixture.example/", "GET", "image")
        with pytest.raises(RuntimeError, match="cap exceeded"):
            await channel.request("https://denied.fixture.example/", "GET", "image")
        assert channel.requests == 64
        for raw in (b"", b"x" * 65536 + b"\n", b"[]\n", b"{}"):
            invalid = channel_type(io.BytesIO(raw), io.StringIO())
            with pytest.raises(RuntimeError):
                await invalid.request("https://denied.fixture.example/", "GET", "image")
            with pytest.raises(RuntimeError, match="cannot be reused"):
                await invalid.request("https://denied.fixture.example/", "GET", "image")

    asyncio.run(exercise())


def test_async_websocket_refusal_awaits_close_without_a_sync_dispatcher() -> None:
    import asyncio
    import io
    from collections.abc import Callable
    from typing import Any, cast

    from playwright.async_api import WebSocketRoute

    namespace = async_guest_namespace()
    channel_type = cast(Any, namespace["FixtureChannel"])
    refuse = cast(Callable[..., Any], namespace["refuse_websocket"])

    class FakeSocket:
        url = "wss://denied.fixture.example/socket"
        closed: tuple[int, str] | None = None

        async def close(self, *, code: int, reason: str) -> None:
            await asyncio.sleep(0)
            self.closed = (code, reason)

    socket = FakeSocket()
    denied: list[str] = []
    channel = channel_type(io.BytesIO(b'{"status":"denied"}\n'), io.StringIO())
    asyncio.run(refuse(cast(WebSocketRoute, socket), channel, denied))
    assert socket.closed == (1008, "synthetic boundary") and denied == ["websocket"]
    guest = (ROOT / "scripts/isolation/browser_acceptance.py").read_text()
    assert "async with async_playwright()" in guest
    assert "from playwright.sync_api" not in guest


def test_cancelled_threaded_read_poisons_channel_before_another_exchange() -> None:
    import asyncio
    import io
    import threading
    from typing import Any, BinaryIO, cast

    import pytest

    channel_type = cast(Any, async_guest_namespace()["FixtureChannel"])
    entered = threading.Event()
    release = threading.Event()

    class OwnedReader:
        def readline(self, size: int) -> bytes:
            assert size == 65537
            entered.set()
            release.wait(2)
            return b'{"status":"denied"}\n'

    channel = channel_type(cast(BinaryIO, OwnedReader()), io.StringIO())

    async def exercise() -> None:
        task = asyncio.create_task(
            channel.request("https://denied.fixture.example/", "GET", "image")
        )
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(RuntimeError, match="cannot be reused"):
                await channel.request("https://denied.fixture.example/", "GET", "image")
            assert channel.requests == 1
        finally:
            release.set()

    asyncio.run(exercise())
