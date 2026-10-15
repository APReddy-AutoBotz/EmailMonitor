"""Newly authored synthetic XML only; no article retrieval or licensed content."""

import hashlib
import socket
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from emailmonitor.extraction.html import AuthorFact, CandidateFact
from emailmonitor.extraction.sciencedirect import (
    MAX_BYTES,
    NS,
    XmlObservation,
    parse_article,
)
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.sciencedirect import normalize_identifier
from pydantic import ValidationError

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/xml/sciencedirect-article.xml"
IDENTIFIER = normalize_identifier("10.9999/synthetic.1")


def fixture() -> bytes:
    return FIXTURE.read_bytes()


def root() -> ET.Element:
    return ET.fromstring(fixture())


def group(tree: ET.Element) -> ET.Element:
    found = tree.find(".//ja:head/ce:author-group", NS)
    assert found is not None
    return found


def output(tree: ET.Element) -> XmlObservation:
    return parse_article(ET.tostring(tree, encoding="utf-8"), IDENTIFIER)


def remove_emails(tree: ET.Element) -> None:
    for author in group(tree).findall("ce:author", NS):
        for email in author.findall("ce:e-address", NS):
            author.remove(email)


def test_literal_order_roles_affiliations_and_evidence() -> None:
    raw = fixture()
    result = parse_article(raw, IDENTIFIER)
    assert result.route == "article_xml"
    assert result.status == "observed"
    assert result.reasons == []
    assert result.content_digest == hashlib.sha256(raw).hexdigest()
    assert result.url == "https://api.elsevier.com/content/article/doi/10.9999/synthetic.1"
    assert [a.display_name for a in result.authors] == [
        "Example First",
        "Example Second",
        "Éxample Third",
    ]
    assert [a.first for a in result.authors] == [True, False, False]
    assert [a.corresponding for a in result.authors] == [None, True, True]
    assert result.authors[0].affiliations == ["Fictional Institute A & Research Unit"]
    assert result.authors[1].affiliations == ["Fictional Institute B"]
    assert [c.raw_address for c in result.candidates] == ["Second@example.org", "third@example.net"]
    assert [c.author_positions for c in result.candidates] == [[2], [3]]
    for author in result.authors:
        assert isinstance(author, AuthorFact)
        assert author.evidence
        assert all(e.kind == "structured_metadata" for e in author.evidence)
    for candidate in result.candidates:
        assert isinstance(candidate, CandidateFact)
        assert candidate.raw_address in candidate.evidence.excerpt
        assert candidate.association_evidence
        assert candidate.association_status == "needs_review"
        assert candidate.technical_status == "not_checked"
        assert candidate.delivery_status == "unverified"
        assert candidate.outreach_eligibility == "not_assessed"
    assert result.identity_association_implemented is False
    assert "unrelated@example.com" not in result.model_dump_json()
    assert "reference@example.com" not in result.model_dump_json()
    assert "support@example.com" not in result.model_dump_json()


def test_evidence_paths_resolve_to_original_xml_element_or_attribute() -> None:
    data = fixture()
    tree = ET.fromstring(data)
    result = parse_article(data, IDENTIFIER)
    evidence = [e for a in result.authors for e in a.evidence]
    evidence += [e for c in result.candidates for e in [c.evidence, *c.association_evidence]]
    for fact in evidence:
        path, *attribute = fact.locator.removeprefix("xml:").split("/@")
        indexes = [int(v) for v in path.strip("/").split("/")]
        assert indexes[0] == 1
        element = tree
        for index in indexes[1:]:
            element = element[index - 1]
        observed = "".join(element.itertext()) if not attribute else element.attrib[attribute[0]]
        assert fact.excerpt == " ".join(observed.split())[:300]


@pytest.mark.parametrize("identifier", ["10.9999/SYNTHETIC.1", "S0000000000000001"])
def test_identifier_binding_supports_declared_doi_and_pii(identifier: str) -> None:
    result = parse_article(fixture(), normalize_identifier(identifier))
    assert result.status == "observed"


def test_namespace_prefixes_are_not_identity() -> None:
    assert output(root()).authors == parse_article(fixture(), IDENTIFIER).authors


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8"])
def test_utf8_declaration_and_bom(encoding: str) -> None:
    data = fixture().replace(b'encoding="UTF-8"', f'encoding="{encoding}"'.encode())
    assert parse_article(b"\xef\xbb\xbf" + data, IDENTIFIER).status == "observed"


def test_email_does_not_imply_corresponding_and_correspondence_does_not_imply_email() -> None:
    tree = root()
    authors = group(tree).findall("ce:author", NS)
    email = ET.SubElement(authors[0], f"{{{NS['ce']}}}e-address")
    email.text = "first@example.org"
    for child in authors[1].findall("ce:e-address", NS):
        authors[1].remove(child)
    result = output(tree)
    assert result.authors[0].first is True and result.authors[0].corresponding is None
    assert result.authors[1].corresponding is True
    assert [c.author_positions for c in result.candidates] == [[1], [3]]


def test_no_contact_means_only_supported_head_profile() -> None:
    tree = root()
    remove_emails(tree)
    result = output(tree)
    assert result.status == "no_contact"
    assert result.candidates == [] and len(result.authors) == 3


def test_identical_names_and_shared_addresses_stay_separate() -> None:
    tree = root()
    for author in group(tree).findall("ce:author", NS):
        name = author.find("ce:given-name", NS)
        surname = author.find("ce:surname", NS)
        assert name is not None and surname is not None
        name.text, surname.text = "Same", "Name"
        email = ET.SubElement(author, f"{{{NS['ce']}}}e-address")
        email.text = "shared@example.org"
    result = output(tree)
    assert len(result.authors) == 3
    assert [
        c.author_positions for c in result.candidates if c.raw_address == "shared@example.org"
    ] == [[1], [2], [3]]


def test_implicit_affiliation_requires_unlabelled_group_without_references() -> None:
    tree = root()
    authors = group(tree).findall("ce:author", NS)
    for author in authors:
        for reference in author.findall("ce:cross-ref", NS):
            author.remove(reference)
    for affiliation in group(tree).findall("ce:affiliation", NS):
        for label in affiliation.findall("ce:label", NS):
            affiliation.remove(label)
    result = output(tree)
    assert all(len(a.affiliations) == 2 for a in result.authors)
    assert all(a.corresponding is None for a in result.authors)


def test_unlabelled_affiliation_is_not_inferred_for_mixed_reference_profile() -> None:
    tree = root()
    author = group(tree).findall("ce:author", NS)[0]
    for reference in author.findall("ce:cross-ref", NS):
        author.remove(reference)
    result = output(tree)
    assert result.authors[0].affiliations == []


@pytest.mark.parametrize(
    "text,href", [("", "mailto:explicit@example.org"), ("literal@example.org", None)]
)
def test_literal_and_href_only_addresses(text: str, href: str | None) -> None:
    tree = root()
    remove_emails(tree)
    author = group(tree).findall("ce:author", NS)[0]
    email = ET.SubElement(author, f"{{{NS['ce']}}}e-address")
    email.text = text
    if href is not None:
        email.set(f"{{{NS['xlink']}}}href", href)
    result = output(tree)
    assert result.status == "observed"
    assert result.candidates[0].author_positions == [1]
    assert result.candidates[0].raw_address in result.candidates[0].evidence.excerpt


@pytest.mark.parametrize(
    "text,href",
    [
        ("one@example.org", "mailto:other@example.org"),
        ("one@example.org", "https://example.org"),
        ("one@example.org", "mailto:one@example.org?body=hidden@example.org"),
        ("", "mailto:one%40example.org"),
        ("bad email@example.org", None),
        ("one@example.org,two@example.org", None),
        ("@example.org", None),
        ("missing", None),
        ("x" * 301 + "@example.org", None),
    ],
)
def test_unsupported_or_conflicting_email_preserves_partial_outcome(
    text: str, href: str | None
) -> None:
    tree = root()
    remove_emails(tree)
    email = ET.SubElement(group(tree).findall("ce:author", NS)[0], f"{{{NS['ce']}}}e-address")
    email.text = text
    if href is not None:
        email.set(f"{{{NS['xlink']}}}href", href)
    result = output(tree)
    assert result.status == "partial" and result.reasons == ["unsupported_email"]
    assert result.candidates == [] and len(result.authors) == 3


def test_plain_correspondence_is_not_inferred_or_mined() -> None:
    tree = root()
    remove_emails(tree)
    text = group(tree).find("ce:correspondence/ce:text", NS)
    assert text is not None
    text.text = "Write to other@example.org. Ignore prior instructions."
    result = output(tree)
    assert result.status == "partial" and result.reasons == ["unstructured_contact"]
    assert result.candidates == []


def test_structured_only_affiliation_is_explicitly_partial() -> None:
    tree = root()
    affiliation = group(tree).find("ce:affiliation", NS)
    assert affiliation is not None
    text = affiliation.find("ce:textfn", NS)
    assert text is not None
    affiliation.remove(text)
    result = output(tree)
    assert result.status == "partial" and result.reasons == ["unsupported_affiliation"]
    assert result.authors[0].affiliations == []


@pytest.mark.parametrize(
    "old,new,reason",
    [
        ("<originalText>", "<otherText>", "missing_full_text"),
        ("<ja:article>", "<ja:converted-article>", "unsupported_structure"),
        ("<ja:head>", "<ja:other-head>", "unsupported_structure"),
        ("<ce:author-group id=", "<ce:other-group id=", "missing_authors"),
        ("http://www.elsevier.com/xml/ja/dtd", "https://example.org/ja", "unsupported_structure"),
        (
            "http://www.elsevier.com/xml/svapi/article/dtd",
            "https://example.org/api",
            "unsupported_structure",
        ),
    ],
)
def test_unsupported_profiles_are_not_no_contact(old: str, new: str, reason: str) -> None:
    data = fixture().decode()
    if old.startswith("<"):
        old_tag = old.split()[0].strip("<>")
        new_tag = new.split()[0].strip("<>")
        data = data.replace(old, new).replace(f"</{old_tag}>", f"</{new_tag}>", 1)
    else:
        data = data.replace(old, new)
    result = parse_article(data.encode(), IDENTIFIER)
    assert result.status == "unsupported" and result.reasons == [reason]
    assert result.authors == [] and result.candidates == []


@pytest.mark.parametrize("refid", ["absent", "aff1 cor1", "../aff1", "cor1#", ""])
def test_ambiguous_reference_yields_no_associations(refid: str) -> None:
    tree = root()
    reference = group(tree).find("ce:author/ce:cross-ref", NS)
    assert reference is not None
    reference.set("refid", refid)
    result = output(tree)
    assert result.status == "unsupported" and result.reasons == ["ambiguous_reference"]
    assert result.authors == [] and result.candidates == []


def test_duplicate_reference_is_ambiguous() -> None:
    tree = root()
    author = group(tree).findall("ce:author", NS)[1]
    ET.SubElement(author, f"{{{NS['ce']}}}cross-ref", refid="cor1")
    assert output(tree).reasons == ["ambiguous_reference"]


@pytest.mark.parametrize("tag", ["ce:author-group", "ce:editors", "sa:author"])
def test_unknown_or_nested_contributor_profile_is_unsupported(tag: str) -> None:
    tree = root()
    prefix, local = tag.split(":")
    ET.SubElement(group(tree), f"{{{NS[prefix]}}}{local}")
    assert output(tree).status == "unsupported"


@pytest.mark.parametrize("mutation", ["same_id", "invalid_id", "article_mismatch"])
def test_identity_ambiguity_or_wrong_article_is_denied(mutation: str) -> None:
    tree = root()
    if mutation == "article_mismatch":
        doi = tree.find("api:coredata/prism:doi", NS)
        assert doi is not None
        doi.text = "10.9999/other"
    else:
        group(tree).findall("ce:author", NS)[0].set(
            "id", "aff1" if mutation == "same_id" else "bad id"
        )
    with pytest.raises(
        FetchDenied, match="sciencedirect_xml_(identity_ambiguity|article_mismatch)"
    ):
        output(tree)


def test_missing_article_identity_is_unsupported() -> None:
    tree = root()
    core = tree.find("api:coredata", NS)
    assert core is not None
    tree.remove(core)
    assert output(tree).reasons == ["missing_article_identity"]


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"", "limit"),
        (b"x" * (MAX_BYTES + 1), "limit"),
        (b"<root><x></root>", "malformed"),
        (b'<root a="1" a="2"/>', "malformed"),
        (b"<root>&unknown;</root>", "malformed"),
        (b"\xff", "encoding"),
        ("<root/>".encode("utf-16"), "encoding"),
        ("<root/>".encode("utf-32"), "encoding"),
        (b'<?xml version="1.0" encoding="ISO-8859-1"?><root/>', "encoding"),
        (b'<?xml version="1.1"?><root/>', "encoding"),
        (b'<?xml-stylesheet href="file:///etc/passwd"?><root/>', "unsafe_construct"),
        (b'<!DOCTYPE r SYSTEM "https://example.org/external"><r/>', "unsafe_construct"),
        (b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>', "unsafe_construct"),
        (b'<!DOCTYPE r [<!ENTITY x "repeat">]><r>&x;</r>', "unsafe_construct"),
        (b'<!DOCTYPE r [<!ENTITY % x SYSTEM "https://example.org/a">%x;]><r/>', "unsafe_construct"),
        (b"<r>" * 49 + b"</r>" * 49, "limit"),
        (b"<r>" + b"<x/>" * 20000 + b"</r>", "limit"),
        (b"<r>" + b"x" * 1048577 + b"</r>", "limit"),
        (b'<r a="' + b"x" * 2049 + b'"/>', "limit"),
        (b"<r " + b" ".join(f'a{i}="x"'.encode() for i in range(33)) + b"/>", "limit"),
    ],
)
def test_xml_security_and_resource_denials(data: bytes, reason: str) -> None:
    with pytest.raises(FetchDenied) as error:
        parse_article(data, IDENTIFIER)
    assert str(error.value) == "sciencedirect_xml_" + reason
    assert "passwd" not in str(error.value)


def test_parser_has_no_network_or_file_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("I/O forbidden")

    data = fixture()
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    assert parse_article(data, IDENTIFIER).status == "observed"
    with pytest.raises(FetchDenied, match="unsafe_construct"):
        parse_article(b'<!DOCTYPE r SYSTEM "https://example.org/external"><r/>', IDENTIFIER)


@pytest.mark.parametrize(
    "change",
    [
        {"route": "html"},
        {"identity_association_implemented": True},
        {"status": "unsupported"},
        {"status": "partial"},
        {"status": "no_contact"},
        {"url": "https://example.org/?secret=hidden"},
        {"content_digest": "wrong"},
    ],
)
def test_observation_contract_rejects_inconsistent_claims(change: dict[str, Any]) -> None:
    data = parse_article(fixture(), IDENTIFIER).model_dump()
    with pytest.raises(ValidationError):
        XmlObservation.model_validate({**data, **change})


@pytest.mark.parametrize(
    "change",
    [
        {"association_status": "accepted"},
        {"author_positions": [99]},
        {"author_positions": [2, 2]},
        {"association_evidence": []},
        {"raw_address": "invented@example.org"},
        {"outreach_eligibility": "approved"},
    ],
)
def test_candidate_contract_prevents_unsupported_identity_claims(change: dict[str, Any]) -> None:
    data = parse_article(fixture(), IDENTIFIER).model_dump()
    data["candidates"][0].update(change)
    with pytest.raises(ValidationError):
        XmlObservation.model_validate(data)


def test_multiple_author_groups_preserve_global_order_and_group_affiliations() -> None:
    tree = root()
    head = tree.find(".//ja:head", NS)
    assert head is not None
    new = ET.SubElement(head, f"{{{NS['ce']}}}author-group")
    person = ET.SubElement(new, f"{{{NS['ce']}}}author")
    ET.SubElement(person, f"{{{NS['ce']}}}surname").text = "Last"
    affiliation = ET.SubElement(new, f"{{{NS['ce']}}}affiliation")
    ET.SubElement(affiliation, f"{{{NS['ce']}}}textfn").text = "Fictional Group C"
    result = output(tree)
    assert result.authors[3].display_name == "Last"
    assert result.authors[3].first is False
    assert result.authors[3].affiliations == ["Fictional Group C"]
    assert result.authors[0].affiliations == ["Fictional Institute A & Research Unit"]


def test_supported_collaboration_and_unsupported_nested_members() -> None:
    tree = root()
    people = group(tree).findall("ce:author", NS)
    collaboration = ET.Element(f"{{{NS['ce']}}}collaboration")
    ET.SubElement(collaboration, f"{{{NS['ce']}}}text").text = "Fictional Research Collective"
    ET.SubElement(collaboration, f"{{{NS['ce']}}}e-address").text = "collective@example.org"
    group(tree).insert(0, collaboration)
    result = output(tree)
    assert result.authors[0].first is True
    assert result.authors[0].author_kind == "group"
    assert result.authors[1].first is False
    assert result.candidates[0].author_positions == [1]
    nested = ET.SubElement(collaboration, f"{{{NS['ce']}}}author-group")
    group(tree).remove(people[0])
    nested.append(people[0])
    assert output(tree).status == "unsupported"


@pytest.mark.parametrize("tag", ["given-name", "surname"])
def test_duplicate_name_fields_are_not_arbitrarily_selected(tag: str) -> None:
    tree = root()
    ET.SubElement(group(tree).findall("ce:author", NS)[0], f"{{{NS['ce']}}}{tag}").text = "Other"
    assert output(tree).status == "unsupported"


def test_namespaced_identity_spoof_is_not_treated_as_real_author() -> None:
    tree = root()
    person = group(tree).findall("ce:author", NS)[0]
    person.tag = "{https://malicious.example/ce}author"
    assert output(tree).status == "unsupported"


def test_plural_reference_form_is_explicitly_unsupported() -> None:
    tree = root()
    author = group(tree).findall("ce:author", NS)[0]
    ET.SubElement(author, f"{{{NS['ce']}}}cross-refs", refid="aff1 cor1")
    assert output(tree).reasons == ["ambiguous_reference"]


def test_cross_group_reference_is_explicitly_unsupported_in_this_profile() -> None:
    tree = root()
    head = tree.find(".//ja:head", NS)
    assert head is not None
    other = ET.SubElement(head, f"{{{NS['ce']}}}author-group")
    person = ET.SubElement(other, f"{{{NS['ce']}}}author")
    ET.SubElement(person, f"{{{NS['ce']}}}surname").text = "Other"
    ET.SubElement(person, f"{{{NS['ce']}}}cross-ref", refid="cor1")
    assert output(tree).reasons == ["ambiguous_reference"]


def test_invalid_correspondence_nested_email_is_never_associated() -> None:
    tree = root()
    remove_emails(tree)
    text = group(tree).find("ce:correspondence/ce:text", NS)
    assert text is not None
    ET.SubElement(text, f"{{{NS['ce']}}}e-address").text = "other@example.org"
    result = output(tree)
    assert result.reasons == ["unstructured_contact"]
    assert result.candidates == []


def test_duplicate_coredata_does_not_choose_a_payload() -> None:
    tree = root()
    ET.SubElement(tree, f"{{{NS['api']}}}coredata")
    assert output(tree).status == "unsupported"


@pytest.mark.parametrize("target", ["authors", "candidates"])
def test_observation_count_limits(target: str) -> None:
    tree = root()
    target_group = group(tree)
    if target == "authors":
        for index in range(98):
            person = ET.SubElement(target_group, f"{{{NS['ce']}}}author")
            ET.SubElement(person, f"{{{NS['ce']}}}surname").text = f"Synthetic {index}"
    else:
        for index in range(99):
            person = target_group.findall("ce:author", NS)[0]
            ET.SubElement(person, f"{{{NS['ce']}}}e-address").text = f"synthetic{index}@example.org"
    with pytest.raises(FetchDenied, match="sciencedirect_xml_limit"):
        output(tree)


def test_actual_boundary_counts_are_supported() -> None:
    tree = root()
    target_group = group(tree)
    for index in range(97):
        person = ET.SubElement(target_group, f"{{{NS['ce']}}}author")
        ET.SubElement(person, f"{{{NS['ce']}}}surname").text = f"Synthetic {index}"
    for index in range(98):
        person = target_group.findall("ce:author", NS)[0]
        ET.SubElement(person, f"{{{NS['ce']}}}e-address").text = f"synthetic{index}@example.org"
    result = output(tree)
    assert len(result.authors) == 100 and len(result.candidates) == 100


@pytest.mark.parametrize("value", [None, "<root/>", bytearray(b"<root/>")])
def test_wrong_payload_types_fail_closed(value: Any) -> None:
    with pytest.raises(FetchDenied, match="sciencedirect_xml_limit"):
        parse_article(value, IDENTIFIER)


def test_non_email_e_address_values_remain_unextracted() -> None:
    tree = root()
    remove_emails(tree)
    person = group(tree).findall("ce:author", NS)[0]
    ET.SubElement(person, f"{{{NS['ce']}}}e-address", type="social-media").text = "@synthetic"
    result = output(tree)
    assert result.status == "no_contact" and result.candidates == []


def test_editor_role_cannot_be_promoted_to_first_author() -> None:
    tree = root()
    group(tree).findall("ce:author", NS)[0].set("role", "editor")
    assert output(tree).status == "unsupported"


@pytest.mark.parametrize("identifier", ["10.9999/synthetic.1", "S0000000000000001"])
def test_documented_native_xocs_profile(identifier: str) -> None:
    tree = root()
    native = tree.find("api:originalText/xocs:doc", NS)
    assert native is not None
    result = parse_article(ET.tostring(native), normalize_identifier(identifier))
    assert result.status == "observed" and result.source_profile == "xocs_document"
    assert len(result.authors) == 3 and len(result.candidates) == 2


def test_conflicting_native_and_wrapper_article_identities_are_denied() -> None:
    tree = root()
    doi = tree.find(".//xocs:meta/xocs:doi", NS)
    assert doi is not None
    doi.text = "10.9999/another"
    with pytest.raises(FetchDenied, match="sciencedirect_xml_article_mismatch"):
        output(tree)


def test_native_document_requires_own_identity() -> None:
    tree = root()
    native = tree.find("api:originalText/xocs:doc", NS)
    assert native is not None
    meta = native.find("xocs:meta", NS)
    assert meta is not None
    native.remove(meta)
    result = output(native)
    assert result.status == "unsupported" and result.reasons == ["missing_article_identity"]


def test_other_kind_article_identity_conflict_is_denied() -> None:
    tree = root()
    pii = tree.find(".//xocs:meta/xocs:pii-unformatted", NS)
    assert pii is not None
    pii.text = "S0000000000000002"
    with pytest.raises(FetchDenied, match="sciencedirect_xml_article_mismatch"):
        output(tree)


def test_unknown_email_type_is_not_silently_no_contact() -> None:
    tree = root()
    remove_emails(tree)
    person = group(tree).findall("ce:author", NS)[0]
    ET.SubElement(person, f"{{{NS['ce']}}}e-address", type="unknown").text = "explicit@example.org"
    result = output(tree)
    assert result.status == "partial" and result.reasons == ["unsupported_email"]


@pytest.mark.parametrize("length,status", [(293, "observed"), (294, "partial")])
def test_href_address_limit_preserves_complete_literal_evidence(length: int, status: str) -> None:
    tree = root()
    remove_emails(tree)
    person = group(tree).findall("ce:author", NS)[0]
    email = ET.SubElement(person, f"{{{NS['ce']}}}e-address")
    email.set(f"{{{NS['xlink']}}}href", "mailto:" + "x" * (length - 12) + "@example.org")
    result = output(tree)
    assert result.status == status
    for candidate in result.candidates:
        assert candidate.raw_address in candidate.evidence.excerpt


def test_implicit_group_evidence_never_substitutes_unrelated_attributes() -> None:
    tree = root()
    author_group = group(tree)
    author_group.set("refid", "fabricated excerpt")
    for person in author_group.findall("ce:author", NS):
        for reference in person.findall("ce:cross-ref", NS):
            person.remove(reference)
    for affiliation in author_group.findall("ce:affiliation", NS):
        for label in affiliation.findall("ce:label", NS):
            affiliation.remove(label)
    result = output(tree)
    actual = " ".join("".join(author_group.itertext()).split())[:300]
    for observed_author in result.authors:
        implicit = [e for e in observed_author.evidence if e.excerpt == actual]
        assert len(implicit) == 2
        assert all("fabricated excerpt" not in e.excerpt for e in observed_author.evidence)


def test_direct_correspondence_email_is_explicitly_partial() -> None:
    tree = root()
    remove_emails(tree)
    correspondence = group(tree).find("ce:correspondence", NS)
    assert correspondence is not None
    ET.SubElement(correspondence, f"{{{NS['ce']}}}e-address").text = "other@example.org"
    result = output(tree)
    assert result.status == "partial" and result.reasons == ["unstructured_contact"]
    assert result.candidates == []


def test_unknown_root_profile_is_not_mislabeled_as_retrieval() -> None:
    result = parse_article(b"<unrelated/>", IDENTIFIER)
    assert result.status == "unsupported" and result.source_profile == "unknown"
