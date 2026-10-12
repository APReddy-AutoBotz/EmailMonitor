"""Approved disposable CI browser; host gateway only contacts synthetic loopback TLS."""

import json
import os
import selectors
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

from dns_fixture_server import server as dns_server
from emailmonitor.config import Settings
from emailmonitor.fetching.browser_fixture import (
    BrowserFixtureMediator,
    validate_applied_profile,
    write_bounded_reply,
)
from emailmonitor.fetching.dns_fixture import DNSFixtureResolver
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
from emailmonitor.sources.policy import Operation
from tls_fixture_server import Response, server

IMAGE = "emailmonitor-browser-diagnostic:local"
PAGE = b"""<!doctype html><html><body><p id="marker">synthetic marker</p>
<button id="reveal">Reveal synthetic marker</button><script>
globalThis.boundaryState = {worker_blocked:false,fetch_denied:false,
                           post_denied:false,allowed_fetch:false};
document.querySelector('#reveal').onclick = async () => {
 const state = globalThis.boundaryState, pending = [], denied = 'https://denied.fixture.example';
 globalThis.boundaryPending = {};
 const track = (label, promise) => {
  globalThis.boundaryPending[label] = 'pending';
  pending.push(promise.then(value => {globalThis.boundaryPending[label]='fulfilled';return value;},
                           error => {globalThis.boundaryPending[label]='rejected';throw error;}));
 };
 document.querySelector('#marker').textContent = 'synthetic marker revealed';
 for (const [tag, attr, path] of [['img','src','image'],['link','href','stylesheet'],
                                  ['script','src','script'],['iframe','src','iframe']]) {
  track(path, new Promise(resolve => {
   const node = document.createElement(tag); if(tag==='link') node.rel='stylesheet';
   node.onload = node.onerror = resolve; node[attr] = denied + '/' + path;
   document.body.append(node);
  }));
 }
 track('fetch_denied', fetch(denied+'/fetch').then(()=>{},()=>{state.fetch_denied=true;}));
 track('fetch_allowed', fetch(location.href).then(r=>r.text()).then(t=>{
  state.allowed_fetch=t.includes('synthetic marker');
 }));
 track('post_denied', fetch(location.href,{method:'POST',body:'synthetic'}).then(
  ()=>{},()=>{state.post_denied=true;}));
 track('xhr', new Promise(resolve=>{const xhr=new XMLHttpRequest();xhr.onload=xhr.onerror=resolve;
                                  xhr.open('GET',denied+'/xhr');xhr.send();}));
 track('websocket', new Promise(resolve=>{const ws=new WebSocket('wss://denied.fixture.example/socket');
                                   ws.onerror=ws.onclose=resolve;}));
 track('service_worker', navigator.serviceWorker.register('/worker.js').then(
  reg=>{state.worker_blocked=!reg;},()=>{state.worker_blocked=true;}));
 window.open(denied+'/popup','_blank');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['synthetic diagnostic']));
 a.download='synthetic-only.txt';document.body.append(a);a.click();
 await Promise.allSettled(pending);globalThis.boundaryReady=true;
};
</script></body></html>"""


def docker(*arguments: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True, timeout=timeout
    )


def authorize(url: SafeURL, operation: Operation) -> None:
    if url.path != "/tooltip.html" or operation != Operation.BROWSER:
        raise FetchDenied("source_policy_denied")


def timeout_evidence(
    requests: int, accepted: int, denied: int, last_request: dict[str, str], stderr: bytes
) -> str:
    """Bounded failure context only; never weakens the deadline or pass gates."""
    summary = {
        "requests": requests,
        "accepted": accepted,
        "denied": denied,
        "last_request": {
            name: last_request.get(name, "")[:limit]
            for name, limit in (("url", 512), ("resource", 64), ("method", 16))
        },
        "guest_stderr": stderr[-2048:].decode(errors="replace"),
    }
    return ("Browser diagnostic deadline exceeded: " + json.dumps(summary))[:16384]


class BrowserMediator(Protocol):
    requests: int
    accepted: int
    denied: int

    def reply(self, raw: bytes) -> bytes: ...


def conversation(identifier: str, mediator: BrowserMediator) -> dict[str, object]:
    process = subprocess.Popen(
        ["docker", "start", "--attach", "--interactive", identifier],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    result: dict[str, object] | None = None
    deadline = time.monotonic() + 60
    buffer = bytearray()
    errors = bytearray()
    total = 0
    last_request: dict[str, str] = {}
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Browser diagnostic deadline exceeded")
                events = selector.select(remaining)
                if not events:
                    raise RuntimeError("Browser diagnostic deadline exceeded")
                for key, _ in events:
                    chunk = os.read(key.fd, 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        if not selector.get_map():
                            raise RuntimeError(
                                "Browser exited before evidence: " + errors.decode(errors="replace")
                            )
                        continue
                    total += len(chunk)
                    if total > 262144:
                        raise RuntimeError("Guest output limit exceeded")
                    if key.data == "stderr":
                        errors.extend(chunk)
                        if len(errors) > 16384:
                            raise RuntimeError("Guest error output limit exceeded")
                        continue
                    buffer.extend(chunk)
                    while b"\n" in buffer:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Browser diagnostic deadline exceeded")
                        raw, _, tail = buffer.partition(b"\n")
                        buffer[:] = tail
                        if len(raw) > 8192:
                            raise RuntimeError("Guest frame limit exceeded")
                        message = json.loads(raw)
                        if message.get("kind") == "request":
                            last_request = {
                                name: str(message.get(name, ""))[:512]
                                for name in ("url", "resource", "method")
                            }
                            if str(message.get("url", "")).endswith("/worker.js"):
                                raise RuntimeError("Blocked service worker reached gateway")
                            write_bounded_reply(
                                process.stdin.fileno(), mediator.reply(bytes(raw)), deadline
                            )
                        elif message.get("kind") == "result":
                            result = message
                        else:
                            raise RuntimeError("Unexpected guest protocol command")
                    if len(buffer) > 8192:
                        raise RuntimeError("Guest frame limit exceeded")
        process.stdin.close()
        if process.wait(timeout=10) != 0 or result is None:
            raise RuntimeError("Browser diagnostic failed")
        if result.get("diagnostic") != "synthetic-browser-boundary":
            raise RuntimeError("Missing actual browser evidence")
        if (
            result.get("requests") != mediator.requests
            or result.get("allowed") != mediator.accepted
        ):
            raise RuntimeError("Gateway/guest counters disagree")
        if mediator.accepted < 2 or mediator.denied < 7:
            raise RuntimeError("Expected real gateway acceptance/denial absent")
        return result
    except RuntimeError as failure:
        if str(failure) == "Browser diagnostic deadline exceeded":
            raise RuntimeError(
                timeout_evidence(
                    mediator.requests,
                    mediator.accepted,
                    mediator.denied,
                    last_request,
                    bytes(errors),
                )
            ) from failure
        raise
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Reviewed disposable CI environment required")
    root = Path(__file__).resolve().parents[2]
    profile = root / "scripts/isolation/seccomp-browser.json"
    docker(
        "build",
        "--platform=linux/amd64",
        "--file",
        str(root / "scripts/isolation/Dockerfile.browser"),
        "--tag",
        IMAGE,
        str(root),
        timeout=600,
    )
    created = docker(
        "create",
        "--interactive",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--security-opt=seccomp=" + str(profile),
        "--read-only",
        "--user=1000:1000",
        "--memory=512m",
        "--memory-swap=512m",
        "--cpus=1.0",
        "--pids-limit=128",
        "--ulimit=nofile=256:256",
        "--ulimit=core=0:0",
        "--shm-size=128m",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
        "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-browser-only",
        "--env=HOME=/tmp/browser-home",
        "--env=XDG_CONFIG_HOME=/tmp/browser-config",
        "--env=CHROME_CONFIG_HOME=/tmp/browser-config",
        "--env=XDG_CACHE_HOME=/tmp/browser-cache",
        IMAGE,
        "python",
        "/app/browser_acceptance.py",
    )
    identifier = created.stdout.strip()
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise RuntimeError("Unexpected owned container identifier")
    try:
        host = json.loads(docker("inspect", identifier).stdout)[0]["HostConfig"]
        if (
            host["NetworkMode"] != "none"
            or host["Privileged"]
            or host["CapAdd"]
            or host["CapDrop"] != ["ALL"]
            or not host["ReadonlyRootfs"]
            or host["Binds"]
            or host["IpcMode"] == "host"
            or host["PidMode"] == "host"
            or host["Memory"] != 536870912
            or host["MemorySwap"] != 536870912
            or host["PidsLimit"] != 128
            or host["ShmSize"] != 134217728
            or host["NanoCpus"] != 1000000000
        ):
            raise RuntimeError("Approved browser restrictions not present")
        validate_applied_profile(host["SecurityOpt"], json.loads(profile.read_text()))
        with tempfile.TemporaryDirectory(prefix="em-browser-tls-") as directory:
            with (
                server(Path(directory), {"/tooltip.html": Response(body=PAGE)}) as (
                    endpoint,
                    calls,
                ),
                dns_server() as (dns_route, dns_queries),
            ):
                gateway = TLSFixtureGateway(
                    Settings(environment="test", fixture_mode=True),
                    endpoint,
                    authorize,
                    FetchLimits(max_bytes=32768, total_seconds=5),
                    DNSFixtureResolver(Settings(environment="test", fixture_mode=True), dns_route),
                )
                mediator = BrowserFixtureMediator(
                    Settings(environment="test", fixture_mode=True), gateway
                )
                evidence = conversation(identifier, mediator)
                if len(dns_queries) != 2 * mediator.accepted:
                    raise RuntimeError("DNS snapshot/gateway counters disagree")
                if len(calls) != mediator.accepted or any(
                    set(headers) != {"Host", "Accept", "Connection"} for headers in calls
                ):
                    raise RuntimeError("Credential forwarding or gateway counter mismatch")
                print(
                    json.dumps(
                        {
                            **evidence,
                            "source_requests": len(calls),
                            "credentials_forwarded": False,
                            "synthetic_dns_queries": len(dns_queries),
                            "dns_selected_destination": False,
                        }
                    )
                )
        state = json.loads(docker("inspect", identifier).stdout)[0]["State"]
        if state["ExitCode"] or state["OOMKilled"] or state["Running"]:
            raise RuntimeError("Browser did not close cleanly")
    finally:
        docker("rm", "--force", identifier)


if __name__ == "__main__":
    main()
