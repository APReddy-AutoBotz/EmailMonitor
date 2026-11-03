"""Actual admission and isolated diagnostic on authored bytes; no real sample access."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from emailmonitor.parsing import affiliation_diagnostic_channel as channel
from emailmonitor.parsing.private_affiliation_diagnostic import (
    PURPOSE,
    REPOSITORY,
    AffiliationDiagnosticRightsDecision,
    PrivateAffiliationDiagnosticManifest,
    evaluate_private_affiliation_diagnostic,
)
from emailmonitor.sources.sciencedirect import normalize_identifier
from xml_image_evidence import require_packaged_image


def test_actual_network_none_affiliation_diagnostic_on_authored_synthetic_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("EM_REQUIRE_XML_INTEGRATION") != "synthetic-test-only":
        pytest.skip("Actual owned curated XML image acceptance requires disposable CI")
    original = channel._docker
    inspected: list[str] = []
    cleaned: list[str] = []

    def checked(*args: str) -> bytes:
        output = original(*args)
        if args[0] == "inspect":
            metadata = json.loads(output)[0]
            require_packaged_image(metadata)
            channel.verify_profile(metadata)
            inspected.append(args[1])
        if args[0] == "rm":
            cleaned.append(args[-1])
        return output

    monkeypatch.setattr(channel, "_docker", checked)
    for index, reference in enumerate(("", '<ce:cross-ref refid="cor"/>')):
        data = f"""<xocs:doc xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd"
            xmlns:ja="http://www.elsevier.com/xml/ja/dtd"
            xmlns:ce="http://www.elsevier.com/xml/common/dtd">
          <xocs:meta><xocs:doi>10.9999/affiliation-isolation</xocs:doi></xocs:meta>
          <xocs:serial-item><ja:article><ja:head><ce:author-group>
            <ce:author><ce:given-name>Synthetic</ce:given-name><ce:surname>First</ce:surname>
              <ce:e-address>first@example.org</ce:e-address>{reference}</ce:author>
            <ce:author><ce:given-name>Synthetic</ce:given-name><ce:surname>Second</ce:surname>
              <ce:e-address>second@example.org</ce:e-address></ce:author>
            <ce:affiliation id="aff"><ce:textfn>Fictional Institute</ce:textfn></ce:affiliation>
            <ce:correspondence id="cor"><ce:text>Synthetic note</ce:text></ce:correspondence>
          </ce:author-group></ja:head></ja:article></xocs:serial-item>
        </xocs:doc>""".encode()
        path = tmp_path / f"synthetic-{index}.norm-xml"
        path.write_bytes(data)
        corpus_path = f"SourceXML/synthetic-{index}.norm-xml"
        # Synthetic provenance and independently supplied synthetic review input
        # exercise composition; neither constitutes an actual corpus clearance.
        manifest = PrivateAffiliationDiagnosticManifest(
            repository=REPOSITORY,
            revision="a" * 40,
            corpus_path=corpus_path,
            evidence_url=f"{REPOSITORY}/blob/{'a' * 40}/{corpus_path}",
            acquired_at="2026-10-01T00:00:00Z",
            byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            requested_identifier=normalize_identifier("10.9999/affiliation-isolation"),
            source_profile="xocs_document",
            purpose=PURPOSE,
        )
        rights = AffiliationDiagnosticRightsDecision(
            manifest.digest(), PURPOSE, "cleared", f"synthetic-diagnostic-review-{index}"
        )
        admitted = evaluate_private_affiliation_diagnostic(path, manifest, rights)
        assert admitted.status == "diagnosed" and admitted.reasons == ()
        result = admitted.diagnostic
        assert result is not None
        assert result.group_count == 1 and result.author_count == 2
        assert result.affiliation_count == result.affiliations_with_direct_textfn == 1
        assert result.author_correspondence_reference_count == int(bool(reference))
        assert result.groups_implicit_disabled_by_reference == int(bool(reference))
        assert result.authors_without_selected_affiliation == (2 if reference else 0)
        for forbidden in ("@", "Fictional", "10.9999", manifest.sha256, str(path)):
            assert forbidden not in result.model_dump_json()
    assert len(inspected) == 4
    assert inspected[0] == inspected[1] and inspected[2] == inspected[3]
    assert inspected[0] != inspected[2]
    assert cleaned == [inspected[0], inspected[2]]
    print("AFFILIATION_DIAGNOSTIC_SYNTHETIC_NETWORK_NONE_COUNTERS")
