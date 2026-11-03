"""Authored synthetic inputs only; counts never establish real-sample causality."""

import hashlib
import json
from xml.etree import ElementTree as ET

import pytest
from emailmonitor.extraction.sciencedirect import MAX_BYTES, NS
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.parsing.affiliation_diagnostic import decode_output, diagnose, encode_output
from emailmonitor.parsing.xml_protocol import XmlExpectation
from test_affiliation_diagnostic_reproduction import IDENTIFIER, synthetic


def expected(data: bytes, profile: str = "xocs_document") -> XmlExpectation:
    return XmlExpectation.model_validate(
        {
            "requested_identifier": IDENTIFIER.model_dump(),
            "content_digest": hashlib.sha256(data).hexdigest(),
            "source_profile": profile,
        }
    )


@pytest.mark.parametrize(
    "reference,labelled,text,vector",
    [
        ("", False, True, [1, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]),
        ("cor", False, True, [1, 2, 1, 1, 0, 0, 1, 0, 2, 1, 0, 0]),
        ("foot", False, True, [1, 2, 1, 1, 0, 0, 0, 1, 2, 1, 0, 0]),
        ("", True, True, [1, 2, 1, 1, 1, 0, 0, 0, 2, 0, 1, 0]),
        ("aff", False, True, [1, 2, 1, 1, 0, 2, 0, 0, 0, 1, 0, 0]),
        ("aff", False, False, [1, 2, 1, 0, 0, 2, 0, 0, 0, 1, 0, 2]),
        ("cor", True, True, [1, 2, 1, 1, 1, 0, 1, 0, 2, 1, 1, 0]),
    ],
)
def test_exact_counter_vectors(
    reference: str, labelled: bool, text: bool, vector: list[int]
) -> None:
    data = synthetic(reference=reference, labelled=labelled, text=text)
    result = diagnose(data, expected(data))
    assert list(result.model_dump(exclude={"profile"}).values()) == vector
    encoded = encode_output(result)
    assert decode_output(encoded) == result
    for forbidden in (
        b"example.org",
        b"Fictional",
        b"10.9999",
        b"xml:/",
        b"Synthetic",
        hashlib.sha256(data).hexdigest().encode(),
    ):
        assert forbidden not in encoded


def test_one_author_reference_does_not_fill_unreferenced_author() -> None:
    tree = ET.fromstring(synthetic(reference="aff"))
    authors = tree.findall(".//ce:author", NS)
    ref = authors[1].find("ce:cross-ref", NS)
    assert ref is not None
    authors[1].remove(ref)
    data = ET.tostring(tree)
    result = diagnose(data, expected(data))
    assert result.author_affiliation_reference_count == 1
    assert result.authors_without_selected_affiliation == 1


def test_reference_suppression_is_group_local() -> None:
    tree = ET.fromstring(synthetic(reference="cor"))
    head = tree.find(".//ja:head", NS)
    other = ET.fromstring(synthetic()).find(".//ce:author-group", NS)
    assert head is not None and other is not None
    for node in other.iter():
        if "id" in node.attrib:
            node.set("id", node.attrib["id"] + "second")
    head.append(other)
    data = ET.tostring(tree)
    result = diagnose(data, expected(data))
    assert result.group_count == 2 and result.author_count == 4
    assert result.groups_implicit_disabled_by_reference == 1
    assert result.authors_without_selected_affiliation == 2


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "multi", "author", "correspondence", "doctype"]
)
def test_unsupported_or_unsafe_input_emits_no_counters(mutation: str) -> None:
    tree = ET.fromstring(synthetic(reference="cor"))
    author = tree.find(".//ce:author", NS)
    ref = tree.find(".//ce:cross-ref", NS)
    assert author is not None and ref is not None
    if mutation == "missing":
        ref.set("refid", "missing")
    elif mutation == "duplicate":
        author.append(ET.fromstring(ET.tostring(ref)))
    elif mutation == "multi":
        ref.tag = f"{{{NS['ce']}}}cross-refs"
    elif mutation == "author":
        ET.SubElement(author, f"{{{NS['ce']}}}unknown")
    elif mutation == "correspondence":
        cor = tree.find(".//ce:correspondence", NS)
        assert cor is not None
        cor.clear()
    data = ET.tostring(tree)
    if mutation == "doctype":
        data = b'<!DOCTYPE x [<!ENTITY value "secret">]>' + data
    with pytest.raises((ValueError, FetchDenied)):
        diagnose(data, expected(data))


def test_wrong_profile_and_digest_refuse() -> None:
    data = synthetic()
    with pytest.raises(ValueError):
        diagnose(data, expected(data, "article_retrieval_response"))
    with pytest.raises(ValueError):
        diagnose(data + b" ", expected(data))
    oversized = b"x" * (MAX_BYTES + 1)
    with pytest.raises(ValueError):
        diagnose(oversized, expected(oversized))


@pytest.mark.parametrize("value", [-1, 20001, True, 1.0, "1", None])
def test_strict_integer_output(value: object) -> None:
    data = synthetic()
    document = diagnose(data, expected(data)).model_dump()
    document["author_count"] = value
    with pytest.raises(ValueError):
        decode_output(json.dumps(document).encode() + b"\n")


def test_closed_canonical_output_rejects_cross_mode_and_duplicate_fields() -> None:
    data = synthetic()
    encoded = encode_output(diagnose(data, expected(data)))
    for value in (
        b'{"profile":"network-none-parser-v1","observation":{}}\n',
        encoded.replace(b'"author_count":2', b'"author_count":2,"author_count":2'),
        encoded.rstrip(),
        encoded + b"\n",
        b"x" * 4097,
        encoded.replace(b'"group_count":1,', b""),
        encoded.replace(b'"group_count":1', b'"extra":"private@example.org","group_count":1'),
    ):
        with pytest.raises(ValueError):
            decode_output(value)


def test_refusal_entrypoint_is_redacted_without_isolation() -> None:
    import os
    import subprocess
    import sys

    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "PYTHONPATH"}}
    from pathlib import Path

    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "emailmonitor.parsing.affiliation_diagnostic_worker"],
        input=synthetic(),
        capture_output=True,
        env=environment,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr == b"AFFILIATION_DIAGNOSTIC_REFUSED\n"


@pytest.mark.parametrize(
    "fault",
    [
        "",
        "private_marker",
        "synthetic_marker",
        "wrong_marker",
        "argument",
        "uid",
        "network",
        "caps",
        "privileges",
        "seccomp",
    ],
)
def test_mocked_guest_isolation_guards(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    import io
    import os
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from emailmonitor.parsing import affiliation_diagnostic_worker as worker
    from emailmonitor.parsing.xml_protocol import encode_input

    data = synthetic(reference="cor")
    stdin = SimpleNamespace(buffer=io.BytesIO(encode_input(data, expected(data))))
    stdout = SimpleNamespace(buffer=io.BytesIO())
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "argv", ["worker", "extra"] if fault == "argument" else ["worker"])
    monkeypatch.setattr(os, "geteuid", lambda: 0 if fault == "uid" else 65532)
    monkeypatch.setattr(
        os, "environ", {"EM_PRIVATE_AFFILIATION_DIAGNOSTIC": "one-file-private-diagnostic"}
    )
    if fault == "private_marker":
        os.environ["EM_PRIVATE_OFFLINE_XML"] = ""
    elif fault == "synthetic_marker":
        os.environ["EM_ISOLATION_DIAGNOSTIC"] = ""
    elif fault == "wrong_marker":
        os.environ["EM_PRIVATE_AFFILIATION_DIAGNOSTIC"] = "wrong"
    status = {
        "CapEff": "1" if fault == "caps" else "0",
        "NoNewPrivs": "0" if fault == "privileges" else "1",
        "Seccomp": "0" if fault == "seccomp" else "2",
    }
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self: "\n".join(f"{key}: {value}" for key, value in status.items()),
    )
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: iter([Path("lo"), Path("eth0")] if fault == "network" else [Path("lo")]),
    )
    if fault:
        with pytest.raises(SystemExit):
            worker.main()
        assert stdout.buffer.getvalue() == b""
        assert stderr.getvalue() == "AFFILIATION_DIAGNOSTIC_REFUSED\n"
        assert stdin.buffer.tell() == 0
    else:
        worker.main()
        assert decode_output(stdout.buffer.getvalue()).authors_without_selected_affiliation == 2
        assert stderr.getvalue() == ""


@pytest.mark.parametrize("kind", ["depth", "nodes", "text"])
def test_parser_resource_limits_still_refuse(kind: str) -> None:
    from emailmonitor.extraction.sciencedirect import MAX_DEPTH, MAX_NODES, MAX_TEXT

    if kind == "depth":
        data = b"<x>" * (MAX_DEPTH + 1) + b"</x>" * (MAX_DEPTH + 1)
    elif kind == "nodes":
        data = b"<x>" + b"<y/>" * MAX_NODES + b"</x>"
    else:
        data = b"<x>" + b"y" * (MAX_TEXT + 1) + b"</x>"
    with pytest.raises(FetchDenied):
        diagnose(data, expected(data))


def test_unselected_duplicate_textfn_counts_presence_without_relaxing_selection() -> None:
    tree = ET.fromstring(synthetic(labelled=True))
    affiliation = tree.find(".//ce:affiliation", NS)
    assert affiliation is not None
    ET.SubElement(affiliation, f"{{{NS['ce']}}}textfn").text = "Second synthetic text"
    data = ET.tostring(tree)
    result = diagnose(data, expected(data))
    assert result.affiliations_with_direct_textfn == 1
    assert result.authors_without_selected_affiliation == 2
    assert result.selected_affiliations_missing_textfn == 0
    label = affiliation.find("ce:label", NS)
    assert label is not None
    affiliation.remove(label)
    data = ET.tostring(tree)
    with pytest.raises(ValueError):
        diagnose(data, expected(data))


def test_selection_edge_counter_overflow_refuses_without_saturation() -> None:
    tree = ET.fromstring(synthetic(text=False))
    group = tree.find(".//ce:author-group", NS)
    assert group is not None
    author = group.find("ce:author", NS)
    assert author is not None
    for _ in range(98):
        group.append(ET.fromstring(ET.tostring(author)))
    for index in range(200):
        ET.SubElement(group, f"{{{NS['ce']}}}affiliation", id=f"extra{index}")
    data = ET.tostring(tree)
    with pytest.raises(ValueError):
        diagnose(data, expected(data))
