"""Only authored synthetic bytes; these tests assert no actual corpus rights."""

import hashlib
import io
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import MAX_BYTES, NS, parse_article
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER
from emailmonitor.extraction.xml_service import fixture_bytes
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing import private_sample, xml_channel
from emailmonitor.parsing.private_sample import (
    PURPOSE,
    REPOSITORY,
    PrivateSampleManifest,
    PrivateSampleResult,
    RightsDecision,
    evaluate_private_sample,
)
from emailmonitor.parsing.xml_protocol import encode_input, read_input
from test_xml_pipeline import profile


def sample() -> bytes:
    native = ET.fromstring(fixture_bytes()).find("api:originalText/xocs:doc", NS)
    assert native is not None
    return ET.tostring(native)


def manifest(data: bytes) -> PrivateSampleManifest:
    path = "SourceXML/S0000000000000001.norm-xml"
    return PrivateSampleManifest(
        repository=REPOSITORY,
        revision="a" * 40,
        corpus_path=path,
        evidence_url=f"{REPOSITORY}/blob/{'a' * 40}/{path}",
        acquired_at="2026-10-01T00:00:00Z",
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        requested_identifier=XML_IDENTIFIER,
        source_profile="xocs_document",
        purpose=PURPOSE,
    )


def decision(value: PrivateSampleManifest) -> RightsDecision:
    # Trusted synthetic test composition, never a clearance for an actual sample.
    return RightsDecision(value.digest(), PURPOSE, "cleared", "synthetic-review-only")


def prepare(tmp_path: Path) -> tuple[Path, bytes, PrivateSampleManifest, RightsDecision]:
    data = sample()
    path = tmp_path / "private.norm-xml"
    path.write_bytes(data)
    value = manifest(data)
    return path, data, value, decision(value)


def never(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Unadmitted sample reached Docker")


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "https://github.com/other/OA-STM-Corpus"),
        ("revision", "master"),
        ("revision", "A" * 40),
        ("corpus_path", "SourceXML/../secret.norm-xml"),
        ("corpus_path", "SourceXML/synthetic.xml"),
        ("corpus_path", "SourceXML/%2e%2e.norm-xml"),
        ("evidence_url", "https://example.com/synthetic"),
        ("acquired_at", "2026-10-01T00:00:00"),
        ("acquired_at", "2099-01-01T00:00:00Z"),
        ("acquired_at", "2026-02-30T00:00:00Z"),
        ("byte_size", 0),
        ("byte_size", MAX_BYTES + 1),
        ("byte_size", True),
        ("sha256", "z" * 64),
        ("source_profile", "article_retrieval_response"),
        ("purpose", "commercial-export"),
        ("requested_identifier", {"kind": "doi", "value": "not-a-doi"}),
        ("approved", True),
    ],
)
def test_invalid_manifest_refuses_before_file_or_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    path, _, original, rights = prepare(tmp_path)
    monkeypatch.setattr(xml_channel, "_docker", never)
    monkeypatch.setattr(private_sample, "_read_regular", never)
    changed = original.model_copy(update={field: value})
    assert evaluate_private_sample(path, changed, rights) == PrivateSampleResult(
        "refused", ("manifest_refused",)
    )


@pytest.mark.parametrize(
    "change",
    [
        {"disposition": "unresolved"},
        {"disposition": "denied"},
        {"disposition": True},
        {"scope": "retention-export"},
        {"manifest_digest": "0" * 64},
        {"review_reference": ""},
        {"review_reference": "arbitrary\ncontent"},
    ],
)
def test_rights_are_external_scoped_review_before_file_or_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    path, _, value, rights = prepare(tmp_path)
    monkeypatch.setattr(xml_channel, "_docker", never)
    monkeypatch.setattr(private_sample, "_read_regular", never)
    assert evaluate_private_sample(path, value, replace(rights, **change)).reasons == (
        "rights_refused",
    )


def test_missing_json_or_replayed_rights_cannot_admit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _, value, rights = prepare(tmp_path)
    monkeypatch.setattr(xml_channel, "_docker", never)
    monkeypatch.setattr(private_sample, "_read_regular", never)
    for untrusted in (None, asdict(rights), {"approved": True}, True):
        assert evaluate_private_sample(path, value, untrusted).reasons == ("rights_refused",)  # type: ignore[arg-type]
    changed = value.model_copy(update={"acquired_at": "2026-10-02T00:00:00Z"})
    assert evaluate_private_sample(path, changed, rights).reasons == ("rights_refused",)
    assert evaluate_private_sample(path, value.model_dump(), rights).reasons == (  # type: ignore[arg-type]
        "manifest_refused",
    )


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "directory",
        "symlink",
        "parent_symlink",
        "fifo",
        "size",
        "digest",
        "relative",
        "traversal",
    ],
)
def test_regular_bounded_local_file_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path, data, value, rights = prepare(tmp_path)
    monkeypatch.setattr(xml_channel, "_docker", never)
    if kind == "missing":
        path.unlink()
    elif kind == "directory":
        path = tmp_path
    elif kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        path = link
    elif kind == "parent_symlink":
        link = tmp_path / "parent"
        link.symlink_to(tmp_path, target_is_directory=True)
        path = link / path.name
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif kind == "size":
        path.write_bytes(data + b" ")
    elif kind == "digest":
        path.write_bytes(b"X" * len(data))
    elif kind == "relative":
        path = Path("relative.norm-xml")
    elif kind == "traversal":
        path = tmp_path / ".." / tmp_path.name / path.name
    assert evaluate_private_sample(path, value, rights).reasons == ("file_refused",)


def docker_double(
    monkeypatch: pytest.MonkeyPatch, output: bytes, *, fault: str = ""
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    image_id, container = "sha256:" + "a" * 64, "b" * 64

    def docker(*args: str) -> bytes:
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": image_id}]).encode()
        if args[0] == "create":
            assert args[-4:] == xml_channel.PRIVATE_COMMAND
            assert "--pull=never" in args
            assert all(flag in args for flag in xml_channel.PROFILE[:-1])
            assert "--env=" + xml_channel.PRIVATE_MARKER in args
            assert xml_channel.PROFILE[-1] not in args
            return container.encode()
        if args[0] == "inspect":
            value = profile()
            config = value["Config"]
            assert isinstance(config, dict)
            config.update(Cmd=list(xml_channel.PRIVATE_COMMAND), Env=[xml_channel.PRIVATE_MARKER])
            if fault == "marker":
                config["Env"] = ["EM_PRIVATE_OFFLINE_XML=wrong"]
            elif fault == "dual_marker":
                config["Env"] = [
                    xml_channel.PRIVATE_MARKER,
                    "EM_ISOLATION_DIAGNOSTIC=synthetic-test-only",
                ]
            elif fault == "command":
                config["Cmd"] = list(xml_channel.COMMAND)
            value.update(
                Image=image_id, State={"Running": False, "ExitCode": 0, "OOMKilled": False}
            )
            return json.dumps([value]).encode()
        assert args == ("rm", "--force", container)
        if fault == "cleanup":
            raise RuntimeError("private@example.org must never escape")
        return b""

    monkeypatch.setattr(xml_channel, "_docker", docker)
    monkeypatch.setattr(xml_channel, "exchange", lambda command, data: output)
    return calls


def envelope(data: bytes) -> bytes:
    value = parse_article(data, XML_IDENTIFIER)
    return (
        json.dumps(
            {"profile": "network-none-parser-v1", "observation": value.model_dump(mode="json")}
        ).encode()
        + b"\n"
    )


def test_same_verified_buffer_protocol_and_only_redacted_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, data, value, rights = prepare(tmp_path)
    calls = docker_double(monkeypatch, envelope(data))
    read = private_sample._read_regular
    buffers: list[bytes] = []

    def read_once(path: Path, value: PrivateSampleManifest) -> bytes:
        result = read(path, value)
        buffers.append(result)
        # A subsequent pathname read would parse different, unverified bytes.
        path.write_bytes(b"not XML")
        return result

    def encode_same(raw: bytes, expected: Any) -> bytes:
        assert raw is buffers[0]
        framed = encode_input(raw, expected)
        recovered, binding = read_input(io.BytesIO(framed))
        assert recovered == data and binding == value.expectation()
        return framed

    monkeypatch.setattr(private_sample, "_read_regular", read_once)
    monkeypatch.setattr(xml_channel, "encode_input", encode_same)
    result = evaluate_private_sample(path, value, rights)
    assert result == PrivateSampleResult("observed", (), 3, 2)
    assert len(buffers) == 1
    assert set(asdict(result)) == {"status", "reasons", "author_count", "candidate_count"}
    assert "@" not in repr(result) and str(path) not in repr(result)
    assert calls[-1] == ("rm", "--force", "b" * 64)


@pytest.mark.parametrize(
    "fault",
    [
        "marker",
        "dual_marker",
        "command",
        "cleanup",
        "malformed",
        "misbound",
        "duplicate",
        "overflow",
    ],
)
def test_untrusted_output_and_control_failures_redacted_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    path, data, value, rights = prepare(tmp_path)
    output = envelope(data)
    if fault == "malformed":
        output = b"private@example.org /private/path"
    elif fault == "misbound":
        output = output.replace(value.sha256.encode(), b"0" * 64)
    elif fault == "duplicate":
        output = output.replace(b'{"profile":', b'{"profile":"secret", "profile":', 1)
    elif fault == "overflow":
        output = b"x" * 131073
    calls = docker_double(monkeypatch, output, fault=fault)
    result = evaluate_private_sample(path, value, rights)
    assert result == PrivateSampleResult("refused", ("parser_refused",))
    assert calls[-1] == ("rm", "--force", "b" * 64)


def test_default_fixture_entry_and_worker_refusals_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xml_channel, "_docker", never)
    for settings in (Settings(), Settings(environment="test", fixture_mode=False)):
        with pytest.raises(IsolationUnavailable):
            xml_channel.parse_isolated(settings, sample())
    for args in ([], ["--private-offline"], ["--private-offline", "extra"], ["--unknown"]):
        completed = subprocess.run(
            [sys.executable, "-m", "emailmonitor.parsing.xml_worker", *args],
            input=b"private@example.org",
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
            timeout=5,
            check=False,
        )
        assert completed.returncode == 1 and completed.stdout == b""
        assert completed.stderr == b"XML_PARSER_REFUSED\n"


@pytest.mark.parametrize("mutate", [False, True])
def test_file_is_read_once_with_platform_cap_and_change_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: bool
) -> None:
    path, data, value, rights = prepare(tmp_path)
    docker_double(monkeypatch, envelope(data))
    fdopen = os.fdopen
    bounds: list[int] = []

    class Reader:
        def __init__(self, descriptor: int, mode: str) -> None:
            self.source = fdopen(descriptor, mode)

        def __enter__(self) -> "Reader":
            self.source.__enter__()
            return self

        def __exit__(self, *args: Any) -> None:
            self.source.__exit__(*args)

        def read(self, bound: int) -> bytes:
            bounds.append(bound)
            result: bytes = self.source.read(bound)
            if mutate:
                path.write_bytes(b"X" * len(data))
            return result

        def fileno(self) -> int:
            return self.source.fileno()

    monkeypatch.setattr(os, "fdopen", Reader)
    result = evaluate_private_sample(path, value, rights)
    assert bounds == [MAX_BYTES + 1]
    if mutate:
        assert result.reasons == ("file_refused",)
    else:
        assert result == PrivateSampleResult("observed", (), 3, 2)


@pytest.mark.parametrize(
    "entry,diagnostic,private",
    [
        ("private", None, None),
        ("private", "synthetic-test-only", None),
        ("private", "synthetic-test-only", "one-file-private-evaluation"),
        ("private", None, "wrong"),
        ("fixture", None, "one-file-private-evaluation"),
        ("fixture", "synthetic-test-only", "one-file-private-evaluation"),
    ],
)
def test_private_and_original_worker_markers_are_not_interchangeable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    diagnostic: str | None,
    private: str | None,
) -> None:
    from emailmonitor.parsing import xml_worker

    parsed: list[bool] = []

    def unexpected_parse(stream: Any) -> Any:
        parsed.append(True)
        raise AssertionError("Wrong marker reached parsing")

    monkeypatch.setattr(xml_worker, "parse_input", unexpected_parse)
    monkeypatch.setattr(os, "geteuid", lambda: 65532)
    monkeypatch.setattr(Path, "read_text", lambda self: "CapEff: 0\nNoNewPrivs: 1\nSeccomp: 2\n")
    monkeypatch.setattr(Path, "iterdir", lambda self: iter([Path("lo")]))
    for name, value in (
        ("EM_ISOLATION_DIAGNOSTIC", diagnostic),
        ("EM_PRIVATE_OFFLINE_XML", private),
    ):
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as stopped:
        (xml_worker.private_main if entry == "private" else xml_worker.main)()
    assert stopped.value.code == 1 and not parsed
    output = capsys.readouterr()
    assert output.out == "" and output.err == "XML_PARSER_REFUSED\n"
