"""Actual private entry on synthetic bytes only; not a real corpus authorization."""

import hashlib
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from emailmonitor.extraction.sciencedirect import NS
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER
from emailmonitor.extraction.xml_service import fixture_bytes
from emailmonitor.parsing import xml_channel
from emailmonitor.parsing.private_sample import (
    PURPOSE,
    REPOSITORY,
    PrivateSampleManifest,
    PrivateSampleResult,
    RightsDecision,
    evaluate_private_sample,
)
from xml_image_evidence import require_packaged_image


def test_actual_network_none_private_entry_on_authored_synthetic_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.environ.get("EM_REQUIRE_XML_INTEGRATION") != "synthetic-test-only":
        pytest.skip("Actual owned curated XML image acceptance requires disposable CI")
    native = ET.fromstring(fixture_bytes()).find("api:originalText/xocs:doc", NS)
    assert native is not None
    data = ET.tostring(native)
    path = tmp_path / "synthetic.norm-xml"
    path.write_bytes(data)
    corpus_path = "SourceXML/S0000000000000001.norm-xml"
    # Explicit test double for provenance/rights, never an actual corpus clearance.
    manifest = PrivateSampleManifest(
        repository=REPOSITORY,
        revision="a" * 40,
        corpus_path=corpus_path,
        evidence_url=f"{REPOSITORY}/blob/{'a' * 40}/{corpus_path}",
        acquired_at="2026-10-01T00:00:00Z",
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        requested_identifier=XML_IDENTIFIER,
        source_profile="xocs_document",
        purpose=PURPOSE,
    )
    rights = RightsDecision(manifest.digest(), PURPOSE, "cleared", "synthetic-review-only")
    original = xml_channel._docker
    inspected: list[str] = []
    cleaned: list[str] = []

    def checked(*args: str) -> bytes:
        output = original(*args)
        if args[0] == "inspect":
            metadata = json.loads(output)[0]
            require_packaged_image(metadata)
            xml_channel.verify_profile(metadata, private_offline=True)
            assert metadata["Config"]["Env"].count(xml_channel.PRIVATE_MARKER) == 1
            inspected.append(args[1])
        if args[0] == "rm":
            cleaned.append(args[-1])
        return output

    monkeypatch.setattr(xml_channel, "_docker", checked)
    assert evaluate_private_sample(path, manifest, rights) == PrivateSampleResult(
        "observed", (), 3, 2
    )
    assert len(inspected) == 2 and inspected[0] == inspected[1]
    assert cleaned == [inspected[0]]
    print("PRIVATE_OFFLINE_SYNTHETIC_NETWORK_NONE_REDACTED_COUNTS")
