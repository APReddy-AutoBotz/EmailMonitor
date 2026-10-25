"""Authored protocol/profile boundaries; pure tests do not establish isolation."""

import json
from io import BytesIO

import pytest
from emailmonitor.extraction.pdf_fixture import DIGESTS, pdf_bytes
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing import pdf_channel, xml_channel
from emailmonitor.parsing.pdf_protocol import PdfExpectation, encode_input, parse_input, read_input
from test_durable_jobs import SETTINGS
from test_xml_pipeline import profile


def expected(name: str = "article-a.pdf") -> PdfExpectation:
    return PdfExpectation(
        url="https://synthetic.publisher.example/" + name, content_digest=DIGESTS[name]
    )


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_authored_pdf_protocol_round_trip(name: str) -> None:
    data = pdf_bytes(name)
    scope = expected(name)
    frame = encode_input(data, scope)
    assert read_input(BytesIO(frame)) == (data, scope)
    observed = parse_input(BytesIO(frame))
    output = (
        json.dumps(
            {"profile": "network-none-parser-v1", "observation": observed.model_dump(mode="json")}
        ).encode()
        + b"\n"
    )
    assert pdf_channel.decode_output(output, data, scope) == observed
    with pytest.raises(ValueError):
        pdf_channel.decode_output(output + b"\n", data, scope)


@pytest.mark.parametrize(
    "mutation", ["bytes", "unknown", "duplicate", "extra", "header_cap", "body_cap", "truncated"]
)
def test_pdf_protocol_refuses_unregistered_or_changed_input(mutation: str) -> None:
    frame = encode_input(pdf_bytes("article-a.pdf"), expected())
    header, data = frame.split(b"\n", 1)
    if mutation == "bytes":
        data += b"changed"
    elif mutation == "unknown":
        header = header.replace(b"article-a.pdf", b"unknown.pdf")
    elif mutation == "duplicate":
        header = header[:-1] + b',"protocol":"authored-pdf-input-v1"}'
    elif mutation == "extra":
        header = header[:-1] + b',"path":"/tmp/source"}'
    elif mutation == "header_cap":
        header += b" " * 1024
    elif mutation == "body_cap":
        data = b"x" * 262145
    else:
        data = data[:-1]
    with pytest.raises(ValueError):
        read_input(BytesIO(header + b"\n" + data))


def test_pdf_profile_keeps_original_isolation_limits_and_exact_command() -> None:
    assert pdf_channel.PROFILE == xml_channel.PROFILE
    metadata = profile()
    config = metadata["Config"]
    assert isinstance(config, dict)
    config["Cmd"] = list(pdf_channel.COMMAND)
    pdf_channel.verify_profile(metadata)
    config["Cmd"] = list(xml_channel.COMMAND)
    with pytest.raises(ValueError):
        pdf_channel.verify_profile(metadata)


def test_injected_proxy_environment_refuses_before_parser_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = profile()
    config = metadata["Config"]
    assert isinstance(config, dict)
    config.update(
        Cmd=list(pdf_channel.COMMAND),
        Env=["HTTPS_PROXY=authored-invalid", "EM_ISOLATION_DIAGNOSTIC=synthetic-test-only"],
    )
    metadata["Image"] = "sha256:" + "a" * 64
    commands: list[tuple[str, ...]] = []

    def docker(*args: str) -> bytes:
        commands.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": metadata["Image"]}]).encode()
        if args[0] == "create":
            return ("b" * 64).encode()
        if args[0] == "inspect":
            return json.dumps([metadata]).encode()
        assert args == ("rm", "--force", "b" * 64)
        return b""

    monkeypatch.setattr(pdf_channel, "_docker", docker)
    with pytest.raises(IsolationUnavailable, match="pdf_container_environment_invalid"):
        pdf_channel._parse_with_client(pdf_bytes("article-a.pdf"), expected(), ())
    assert commands[-1] == ("rm", "--force", "b" * 64)
    assert not any(c[0] == "start" for c in commands)


def test_parser_client_config_is_private_scoped_and_removed_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    keys = (
        "DOCKER_CONFIG",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    calls: list[tuple[str, ...]] = []
    directories: list[Path] = []

    def docker(*args: str) -> bytes:
        calls.append(args)
        assert args == ("context", "inspect")
        return json.dumps(
            [
                {
                    "Name": "default",
                    "Endpoints": {
                        "docker": {"Host": "unix:///var/run/docker.sock", "SkipTLSVerify": False}
                    },
                }
            ]
        ).encode()

    def parser(data: bytes, scope: PdfExpectation, prefix: tuple[str, ...]) -> object:
        assert data == pdf_bytes("article-a.pdf") and scope == expected()
        assert prefix[0] == "--config"
        assert prefix[2:] == ("--host", "unix:///var/run/docker.sock")
        path = Path(prefix[1])
        directories.append(path)
        assert path.stat().st_mode & 0o777 == 0o700
        assert (path / "config.json").read_text() == "{}\n"
        assert [p.name for p in path.iterdir()] == ["config.json"]
        raise IsolationUnavailable("authored_parser_failure")

    monkeypatch.setattr(pdf_channel, "_docker", docker)
    monkeypatch.setattr(pdf_channel, "_parse_with_client", parser)
    with pytest.raises(IsolationUnavailable, match="authored_parser_failure"):
        pdf_channel.parse_isolated(SETTINGS, pdf_bytes("article-a.pdf"), expected=expected())
    assert calls == [("context", "inspect")]
    assert len(directories) == 1 and not directories[0].exists()


@pytest.mark.parametrize(
    "key",
    ["DOCKER_CONFIG", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"],
)
def test_parser_client_refuses_endpoint_selection_overrides(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv(key, "authored-override")
    with pytest.raises(IsolationUnavailable, match="pdf_client_endpoint_unverified"):
        pdf_channel.parse_isolated(SETTINGS, pdf_bytes("article-a.pdf"), expected=expected())


@pytest.mark.parametrize(
    "endpoint",
    [
        {
            "Name": "remote",
            "Endpoints": {
                "docker": {"Host": "unix:///var/run/docker.sock", "SkipTLSVerify": False}
            },
        },
        {
            "Name": "default",
            "Endpoints": {"docker": {"Host": "tcp://127.0.0.1:2375", "SkipTLSVerify": False}},
        },
        {
            "Name": "default",
            "Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock", "SkipTLSVerify": True}},
        },
    ],
)
def test_parser_client_refuses_changed_context_or_endpoint(
    monkeypatch: pytest.MonkeyPatch, endpoint: dict[str, object]
) -> None:
    for key in (
        "DOCKER_CONFIG",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(pdf_channel, "_docker", lambda *args: json.dumps([endpoint]).encode())
    with pytest.raises(IsolationUnavailable, match="pdf_client_endpoint_unverified"):
        pdf_channel.parse_isolated(SETTINGS, pdf_bytes("article-a.pdf"), expected=expected())


def test_every_parser_control_and_start_use_same_explicit_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = ("--config", "/authored/private/config", "--host", "unix:///var/run/docker.sock")
    metadata = profile()
    config = metadata["Config"]
    assert isinstance(config, dict)
    config.update(
        Cmd=list(pdf_channel.COMMAND), Env=["EM_ISOLATION_DIAGNOSTIC=synthetic-test-only"]
    )
    metadata["Image"] = "sha256:" + "a" * 64
    metadata["State"] = {"Running": False, "ExitCode": 0, "OOMKilled": False}
    calls: list[tuple[str, ...]] = []
    parsed = parse_input(BytesIO(encode_input(pdf_bytes("article-a.pdf"), expected())))

    def docker(*args: str) -> bytes:
        assert args[:4] == prefix
        command = args[4:]
        calls.append(command)
        if command[:2] == ("image", "inspect"):
            return json.dumps([{"Id": metadata["Image"]}]).encode()
        if command[0] == "create":
            assert command[1:3] == ("--pull=never", "--interactive")
            assert command[3 : 3 + len(pdf_channel.PROFILE)] == pdf_channel.PROFILE
            return ("b" * 64).encode()
        if command[0] == "inspect":
            return json.dumps([metadata]).encode()
        assert command == ("rm", "--force", "b" * 64)
        return b""

    def exchange(command: list[str], data: bytes) -> bytes:
        assert command == ["docker", *prefix, "start", "--attach", "--interactive", "b" * 64]
        assert data == encode_input(pdf_bytes("article-a.pdf"), expected())
        return (
            json.dumps(
                {"profile": "network-none-parser-v1", "observation": parsed.model_dump(mode="json")}
            ).encode()
            + b"\n"
        )

    monkeypatch.setattr(pdf_channel, "_docker", docker)
    monkeypatch.setattr(pdf_channel, "exchange", exchange)
    assert pdf_channel._parse_with_client(pdf_bytes("article-a.pdf"), expected(), prefix) == parsed
    assert calls[-1] == ("rm", "--force", "b" * 64)


@pytest.mark.parametrize("requested", ["tag:mutable", "sha256:" + "a" * 64])
def test_pinned_pdf_image_must_be_immutable_and_match_inspection(
    monkeypatch: pytest.MonkeyPatch, requested: str
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> bytes:
        calls.append(args)
        assert args == ("image", "inspect", requested)
        return json.dumps([{"Id": "sha256:" + "b" * 64}]).encode()

    monkeypatch.setattr(pdf_channel, "_docker", docker)
    with pytest.raises(IsolationUnavailable, match="pdf_image_identity_"):
        pdf_channel._parse_with_client(
            pdf_bytes("article-a.pdf"), expected(), (), image_id=requested
        )
    assert not any("create" in call for call in calls)
