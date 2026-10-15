"""Pure channel/retention/refusal tests; actual sandbox→database proof is separate."""

import json
import sys
from pathlib import Path
from uuid import UUID

import pytest
from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.models import Review
from emailmonitor.associations.review import apply_review
from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import parse_article
from emailmonitor.extraction.xml_retained import (
    XML_DIGEST,
    XML_IDENTIFIER,
    XML_URL,
    RetainedXml,
    XmlBinding,
    retain_xml,
)
from emailmonitor.extraction.xml_service import fixture_bytes
from emailmonitor.fetching.fixture import ByteResponse, FixtureByteTransport, FixtureGateway
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.parsing.xml_channel import (
    COMMAND,
    PROFILE,
    decode_output,
    exchange,
    verify_profile,
)
from emailmonitor.sources.policy import Operation
from pydantic import ValidationError

SETTINGS = Settings(environment="test", fixture_mode=True)
ROOT = Path(__file__).resolve().parents[3]


def retained(excerpts: bool = True) -> RetainedXml:
    raw = parse_article(fixture_bytes(), XML_IDENTIFIER)
    return retain_xml(
        raw,
        XmlBinding(
            organization=UUID(int=1),
            job=UUID(int=2),
            item=UUID(int=3),
            generation=1,
            deletion_generation=1,
            policy_version=1,
            discovery_revision=1,
        ),
        excerpts,
    )


def envelope() -> bytes:
    raw = parse_article(fixture_bytes(), XML_IDENTIFIER)
    return (
        json.dumps(
            {"profile": "network-none-parser-v1", "observation": raw.model_dump(mode="json")}
        ).encode()
        + b"\n"
    )


def test_raw_observations_retained_without_host_xml_reparse() -> None:
    value = decode_output(envelope(), fixture_bytes())
    assert value.content_digest == XML_DIGEST
    document = retained()
    assert document.url == XML_URL and document.canonical_url != XML_URL
    assert len(document.model_dump_json().encode()) < 131072
    bundle = map_observation(SETTINGS, UUID(int=1), document)
    assert len(bundle.authors) == 3 and len(bundle.candidates) == 2
    assert {a.state for a in bundle.associations} == {"needs_review"}
    assert all(c.address.domain_status == "not_checked" for c in bundle.candidates)
    assert all(c.address.outreach_eligibility == "not_assessed" for c in bundle.candidates)
    original = {e.locator for c in document.candidates for e in c.association_evidence}
    assert original <= {e.locator for e in bundle.evidence}
    association = bundle.associations[0]
    revised = apply_review(
        SETTINGS,
        bundle,
        Review(
            association_id=association.id,
            expected_revision=1,
            action="accept",
            evidence_ids=association.evidence_ids,
            reason="Explicit source evidence inspected",
        ),
    )
    assert revised.associations[0].state == "accepted"


def test_locator_only_retention_cannot_accept() -> None:
    document = retained(False)
    assert not document.excerpts_retained
    bundle = map_observation(SETTINGS, UUID(int=1), document)
    assert all(not e.excerpt for e in bundle.evidence)
    association = bundle.associations[0]
    with pytest.raises(ValueError, match="retained"):
        apply_review(
            SETTINGS,
            bundle,
            Review(
                association_id=association.id,
                expected_revision=1,
                action="accept",
                evidence_ids=association.evidence_ids,
                reason="Cannot inspect missing evidence",
            ),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_digest", "0" * 64),
        ("acquisition_digest", "0" * 64),
        ("canonical_url", XML_URL),
        ("source_profile", "xocs_document"),
        ("route", "html"),
        ("url", "https://synthetic.publisher.example/article-a.html"),
        ("isolation_profile", "other"),
        ("requested_identifier", {"kind": "doi", "value": "10.9999/other"}),
        ("excerpts_retained", False),
    ],
)
def test_retained_provenance_tamper_rejected(field: str, value: object) -> None:
    document = retained().model_dump(mode="json")
    document[field] = value
    with pytest.raises(ValidationError):
        RetainedXml.model_validate_json(json.dumps(document))


@pytest.mark.parametrize("suffix", [b"{}", b"garbage", b"\n", b" ", b"\x00"])
def test_trailing_parser_output_rejected(suffix: bytes) -> None:
    with pytest.raises(ValueError):
        decode_output(envelope() + suffix, fixture_bytes())


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"{}\n",
        b"[]\n",
        b"{",
        b"x" * 131073,
        b'{"profile":"network-none-parser-v1","profile":"network-none-parser-v1","observation":{}}\n',
    ],
)
def test_malformed_bounded_output_rejected(output: bytes) -> None:
    with pytest.raises(ValueError):
        decode_output(output, fixture_bytes())


def test_output_digest_and_profile_are_checked() -> None:
    with pytest.raises(ValueError, match="provenance"):
        decode_output(envelope(), fixture_bytes() + b" ")
    with pytest.raises(ValueError, match="profile"):
        decode_output(envelope().replace(b"network-none-parser-v1", b"other"), fixture_bytes())


@pytest.mark.parametrize(
    "script,reason",
    [
        ("import sys;sys.stdin.buffer.read();sys.stdout.write('x'*131073)", "output_limit"),
        ("import sys;sys.stdin.buffer.read();sys.stderr.write('x'*4097)", "output_limit"),
        ("import sys;sys.stdin.buffer.read();sys.exit(4)", "failed"),
        ("import sys,time;sys.stdin.buffer.read();time.sleep(1)", "timeout"),
    ],
)
def test_pipe_failure_boundaries(script: str, reason: str) -> None:
    with pytest.raises(IsolationUnavailable, match=reason):
        exchange([sys.executable, "-c", script], b"synthetic", timeout=0.2)


def test_pipe_exact_success() -> None:
    assert (
        exchange(
            [
                sys.executable,
                "-c",
                "import sys;data=sys.stdin.buffer.read();sys.stdout.buffer.write(data)",
            ],
            b"synthetic",
        )
        == b"synthetic"
    )


def test_xml_media_is_explicit_not_html() -> None:
    for media, operation, allowed in [
        ("application/xml", Operation.XML, True),
        ("text/html", Operation.XML, False),
        ("application/xml", Operation.HTML, False),
    ]:
        transport = FixtureByteTransport(
            SETTINGS, {XML_URL: ByteResponse(200, (b"<x/>",), content_type=media)}
        )
        gateway = FixtureGateway(SETTINGS, transport, lambda u, o: None)
        if allowed:
            assert gateway.fetch(XML_URL, operation) == b"<x/>"
        else:
            with pytest.raises(FetchDenied, match="content_type"):
                gateway.fetch(XML_URL, operation)


def profile() -> dict[str, object]:
    return {
        "HostConfig": {
            "NetworkMode": "none",
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "ReadonlyRootfs": True,
            "Memory": 134217728,
            "MemorySwap": 134217728,
            "PidsLimit": 32,
            "NanoCpus": 500000000,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
            "Ulimits": [
                {"Name": "nofile", "Hard": 64, "Soft": 64},
                {"Name": "core", "Hard": 0, "Soft": 0},
            ],
        },
        "Config": {"User": "65532:65532", "Cmd": list(COMMAND)},
    }


def test_inherited_profile_and_no_mount_credentials() -> None:
    verify_profile(profile())
    old = (ROOT / "scripts/isolation/run_parser_acceptance.py").read_text()
    assert all(repr(flag).replace("'", '"') in old for flag in PROFILE)
    assert COMMAND == ("python", "-m", "emailmonitor.parsing.xml_worker")


@pytest.mark.parametrize(
    "key,value",
    [
        ("NetworkMode", "host"),
        ("Privileged", True),
        ("CapAdd", ["SYS_ADMIN"]),
        ("Binds", ["/tmp:/tmp"]),
        ("Memory", 268435456),
        ("SecurityOpt", ["seccomp=unconfined"]),
        ("ReadonlyRootfs", False),
    ],
)
def test_isolation_profile_changes_fail_closed(key: str, value: object) -> None:
    document = profile()
    host = document["HostConfig"]
    assert isinstance(host, dict)
    host[key] = value
    with pytest.raises(ValueError):
        verify_profile(document)


def test_retained_contract_schema_and_examples() -> None:
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads((ROOT / "contracts/xml-retained-observation.schema.json").read_text())
    expected = RetainedXml.model_json_schema()
    assert {k: v for k, v in schema.items() if k not in ("$schema", "$id")} == expected
    example = json.loads((ROOT / "contracts/examples/xml-retained-observation.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    assert RetainedXml.model_validate_json(json.dumps(example)) == retained()
    policy_schema = json.loads((ROOT / "contracts/source-policy.schema.json").read_text())
    policy = json.loads((ROOT / "contracts/examples/xml-source-policy.json").read_text())
    Draft202012Validator(policy_schema, format_checker=FormatChecker()).validate(policy)
    assert "fetch_html" not in policy["allowed_operations"]


@pytest.mark.parametrize(
    "status,reasons", [("unsupported", ["missing_authors"]), ("partial", ["unsupported_email"])]
)
def test_explicit_gap_retention_and_sql_outcome(status: str, reasons: list[str]) -> None:
    from emailmonitor.extraction.sciencedirect import XmlObservation

    data = parse_article(fixture_bytes(), XML_IDENTIFIER).model_dump()
    data.update(status=status, reasons=reasons, candidates=[])
    if status == "unsupported":
        data["authors"] = []
    value = retain_xml(XmlObservation.model_validate(data), retained().binding, True)
    assert value.excerpts_retained == (status == "partial")
    from emailmonitor.extraction.xml_service import require_current_binding

    require_current_binding(value, value.binding, True)
    bundle = map_observation(SETTINGS, UUID(int=1), value)
    assert not bundle.associations
    sql = (ROOT / "services/backend/migrations/versions/0012_xml_pipeline.sql").read_text()
    assert f"status'='{status}' THEN target:='unsupported'" in sql


def test_migration_preserves_latest_lifecycle_and_html_guards() -> None:
    import re

    previous = (ROOT / "services/backend/migrations/versions/0011_lifecycle.sql").read_text()
    current = (ROOT / "services/backend/migrations/versions/0012_xml_pipeline.sql").read_text()
    assert "GRANT " not in current and "CREATE POLICY" not in current
    assert "DISABLE" not in current and "DROP TABLE" not in current
    for name in (
        "execution_read_allowed",
        "association_visible",
        "guard_article_observation",
        "source_resource_claim",
        "network_entitlement_allowed",
    ):
        before = re.search(
            r"CREATE OR REPLACE FUNCTION emailmonitor\." + name + r"\([\s\S]*?\$\$;", previous
        )
        after = re.search(
            r"CREATE OR REPLACE FUNCTION emailmonitor\." + name + r"\([\s\S]*?\$\$;", current
        )
        assert before is not None and after is not None
        for line in before[0].splitlines():
            if any(
                word in line
                for word in (
                    "privacy_",
                    "lifecycle_",
                    "FOR SHARE NOWAIT",
                    "session_hash",
                    "lease_until",
                )
            ):
                assert line in after[0]
    for digest in (
        "33c3bddb62834da34acb300b7c0bd7bb4c8728fb57e5ece43b8fc4e81920c3f0",
        "7c26b49fe73a02899f77c88ebea70abb1f256399b66ed9c3b41eab12b587f9e3",
    ):
        assert digest in current


def test_host_channel_resolves_local_image_no_pull_and_always_cleans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emailmonitor.parsing import xml_channel

    calls: list[tuple[str, ...]] = []
    image_id = "sha256:" + "a" * 64
    container = "b" * 64

    def docker(*args: str) -> bytes:
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": image_id}]).encode()
        if args[0] == "create":
            assert "--pull=never" in args and image_id in args
            assert "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-test-only" in args
            assert args[-3:] == COMMAND
            return container.encode()
        if args[0] == "inspect":
            document = profile()
            document.update(
                Image=image_id, State={"Running": False, "ExitCode": 0, "OOMKilled": False}
            )
            return json.dumps([document]).encode()
        assert args == ("rm", "--force", container)
        return b""

    monkeypatch.setattr(xml_channel, "_docker", docker)
    monkeypatch.setattr(xml_channel, "exchange", lambda command, data: envelope())
    assert xml_channel.parse_isolated(SETTINGS, fixture_bytes()).content_digest == XML_DIGEST
    assert calls[0] == ("image", "inspect", "emailmonitor-parser-diagnostic:local")
    assert calls[-1] == ("rm", "--force", container)


@pytest.mark.parametrize(
    "mount",
    [
        {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/socket"},
        {"Type": "volume", "Source": "credentials", "Destination": "/secrets"},
        {"Type": "tmpfs", "Destination": "/other"},
    ],
)
def test_unapproved_mount_type_cannot_enter_parser(mount: dict[str, str]) -> None:
    document = profile()
    document["Mounts"] = [mount]
    with pytest.raises(ValueError):
        verify_profile(document)
