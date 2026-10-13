import json
from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.browser_fixture import BrowserFixtureRequest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "change",
    [
        {"url": "x" * 2049},
        {"method": "POST"},
        {"headers": {"Cookie": "synthetic"}},
        {"body": "command"},
        {"identifier": 0},
        {"identifier": True},
        {"resource": "websocket"},
        {"resource": "script"},
        {"kind": "configure"},
        {"resource": "service_worker"},
    ],
)
def test_browser_ipc_is_identifier_and_read_only_resource_bounded(
    change: dict[str, object],
) -> None:
    body = {
        "kind": "request",
        "identifier": 1,
        "url": "https://synthetic.publisher.example/tooltip.html",
        "method": "GET",
        "resource": "document",
        **change,
    }
    with pytest.raises(ValidationError):
        BrowserFixtureRequest.model_validate_json(json.dumps(body))


def test_browser_protocol_valid_request_preserves_no_caller_headers_or_context() -> None:
    request = BrowserFixtureRequest.model_validate_json(
        json.dumps(
            {
                "kind": "request",
                "identifier": 1,
                "url": "https://synthetic.publisher.example/tooltip.html",
                "method": "GET",
                "resource": "fetch",
            }
        )
    )
    assert request.model_dump() == {
        "kind": "request",
        "identifier": 1,
        "url": "https://synthetic.publisher.example/tooltip.html",
        "method": "GET",
        "resource": "fetch",
    }
    assert Settings().environment == "production"


def test_mediator_actual_tls_acceptance_and_denials(tmp_path: Path) -> None:
    import base64

    from emailmonitor.fetching.browser_fixture import BrowserFixtureMediator
    from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
    from emailmonitor.sources.policy import Operation
    from tls_fixture_server import Response, server

    settings = Settings(environment="test", fixture_mode=True)
    operations: list[Operation] = []
    body = {
        "kind": "request",
        "identifier": 1,
        "url": "https://synthetic.publisher.example/tooltip.html",
        "method": "GET",
        "resource": "document",
    }
    with server(tmp_path, {"/tooltip.html": Response()}) as (endpoint, calls):
        mediator = BrowserFixtureMediator(
            settings,
            TLSFixtureGateway(
                settings,
                endpoint,
                lambda url, op: operations.append(op),
                diagnostic_transport_only=True,
            ),
        )
        accepted = json.loads(mediator.reply(json.dumps(body).encode()))
        assert base64.b64decode(accepted["body"]) == b"<p>synthetic observation</p>"
        assert operations == [Operation.BROWSER, Operation.BROWSER]
        for change in (
            {"url": "https://denied.fixture.example/"},
            {"method": "POST"},
            {"resource": "websocket"},
            {"headers": {"Cookie": "synthetic"}},
        ):
            assert json.loads(mediator.reply(json.dumps({**body, **change}).encode())) == {
                "status": "denied"
            }
        assert mediator.accepted == 1 and mediator.denied == 4 and len(calls) == 1
        assert set(calls[0]) == {"Host", "Accept", "Connection"}


def test_mediator_caps_and_production_refusal(tmp_path: Path) -> None:
    from emailmonitor.fetching.browser_fixture import BrowserFixtureMediator
    from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
    from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
    from tls_fixture_server import Response, server

    settings = Settings(environment="test", fixture_mode=True)
    with server(tmp_path, {"/tooltip.html": Response()}) as (endpoint, calls):
        gateway = TLSFixtureGateway(
            settings, endpoint, lambda url, op: None, diagnostic_transport_only=True
        )
        with pytest.raises(IsolationUnavailable):
            BrowserFixtureMediator(Settings(), gateway)
        mediator = BrowserFixtureMediator(settings, gateway)
        for _ in range(64):
            assert mediator.reply(b"{}") == b'{"status":"denied"}\n'
        with pytest.raises(FetchDenied):
            mediator.reply(b"{}")
        with pytest.raises(FetchDenied):
            BrowserFixtureMediator(settings, gateway).reply(b"x" * 8193)
        assert calls == []


def test_docker_applied_profile_json_must_match_and_unconfined_paths_are_denied() -> None:
    from emailmonitor.fetching.browser_fixture import validate_applied_profile
    from emailmonitor.fetching.safety import FetchDenied

    profile: dict[str, object] = {"defaultAction": "SCMP_ACT_ERRNO", "syscalls": []}
    validate_applied_profile(["no-new-privileges", "seccomp=" + json.dumps(profile)], profile)
    for options in (
        ["no-new-privileges", "seccomp=unconfined"],
        ["no-new-privileges", "seccomp=/path/profile.json"],
        ["seccomp=" + json.dumps(profile)],
        ["no-new-privileges", 'seccomp={"defaultAction":"SCMP_ACT_ALLOW"}'],
    ):
        with pytest.raises(FetchDenied):
            validate_applied_profile(options, profile)


def test_owned_reply_pipe_writes_without_buffering() -> None:
    import os
    import time

    from emailmonitor.fetching.browser_fixture import write_bounded_reply

    reader, writer = os.pipe()
    try:
        write_bounded_reply(writer, b"synthetic\n", time.monotonic() + 1)
        assert os.read(reader, 10) == b"synthetic\n"
        assert not os.get_blocking(writer)
    finally:
        os.close(reader)
        os.close(writer)


@pytest.mark.parametrize("prefill", [False, True])
def test_owned_reply_pipe_stalled_reader_obeys_absolute_deadline(prefill: bool) -> None:
    import fcntl
    import os
    import time

    from emailmonitor.fetching.browser_fixture import write_bounded_reply

    reader, writer = os.pipe()
    try:
        # Reduce only this owned test pipe, making partial writes deterministic.
        fcntl.fcntl(writer, fcntl.F_SETPIPE_SZ, 4096)
        os.set_blocking(writer, False)
        if prefill:
            while True:
                try:
                    os.write(writer, b"x" * 4096)
                except BlockingIOError:
                    break
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="deadline exceeded"):
            write_bounded_reply(writer, b"x" * 65536, started + 0.05)
        assert time.monotonic() - started < 1
    finally:
        os.close(reader)
        os.close(writer)


@pytest.mark.parametrize("expired", [False, True])
def test_owned_reply_pipe_rejects_oversize_or_expired_reply(expired: bool) -> None:
    import os
    import time

    from emailmonitor.fetching.browser_fixture import write_bounded_reply

    reader, writer = os.pipe()
    try:
        with pytest.raises(
            RuntimeError, match="deadline exceeded" if expired else "limit exceeded"
        ):
            write_bounded_reply(
                writer,
                b"x" if expired else b"x" * 65537,
                time.monotonic() - 1 if expired else time.monotonic() + 1,
            )
        os.set_blocking(reader, False)
        with pytest.raises(BlockingIOError):
            os.read(reader, 1)
    finally:
        os.close(reader)
        os.close(writer)
