"""Authored synthetic counterfactuals, never real article reproduction bytes."""

from xml.etree import ElementTree as ET

import pytest
from emailmonitor.extraction.sciencedirect import NS, parse_article
from emailmonitor.sources.sciencedirect import normalize_identifier

IDENTIFIER = normalize_identifier("10.9999/affiliation-counterfactual")


def synthetic(*, reference: str = "", labelled: bool = False, text: bool = True) -> bytes:
    root = ET.Element(f"{{{NS['xocs']}}}doc")
    meta = ET.SubElement(root, f"{{{NS['xocs']}}}meta")
    ET.SubElement(meta, f"{{{NS['xocs']}}}doi").text = IDENTIFIER.value
    parent = root
    for prefix, tag in [
        ("xocs", "serial-item"),
        ("ja", "article"),
        ("ja", "head"),
        ("ce", "author-group"),
    ]:
        parent = ET.SubElement(parent, f"{{{NS[prefix]}}}{tag}")
    for index in range(2):
        author = ET.SubElement(parent, f"{{{NS['ce']}}}author")
        ET.SubElement(author, f"{{{NS['ce']}}}given-name").text = "Synthetic"
        ET.SubElement(author, f"{{{NS['ce']}}}surname").text = f"Person {index}"
        ET.SubElement(author, f"{{{NS['ce']}}}e-address").text = f"person{index}@example.org"
        if reference and (index == 0 or reference == "aff"):
            ET.SubElement(author, f"{{{NS['ce']}}}cross-ref", refid=reference)
    aff = ET.SubElement(parent, f"{{{NS['ce']}}}affiliation", id="aff")
    if labelled:
        ET.SubElement(aff, f"{{{NS['ce']}}}label").text = "a"
    if text:
        ET.SubElement(aff, f"{{{NS['ce']}}}textfn").text = "Authored Fictional Institute"
    for tag, identity in [("correspondence", "cor"), ("footnote", "foot")]:
        target = ET.SubElement(parent, f"{{{NS['ce']}}}{tag}", id=identity)
        ET.SubElement(target, f"{{{NS['ce']}}}text").text = "Synthetic note"
    encoded = ET.tostring(root, encoding="utf-8")
    assert isinstance(encoded, bytes)
    return encoded


@pytest.mark.parametrize(
    "reference,labelled,text,status,affiliations",
    [
        ("", False, True, "observed", [1, 1]),
        ("cor", False, True, "partial", [0, 0]),
        ("foot", False, True, "partial", [0, 0]),
        ("", True, True, "partial", [0, 0]),
        ("aff", False, True, "observed", [1, 1]),
        ("aff", False, False, "partial", [0, 0]),
    ],
)
def test_synthetic_affiliation_counterfactuals(
    reference: str, labelled: bool, text: bool, status: str, affiliations: list[int]
) -> None:
    result = parse_article(synthetic(reference=reference, labelled=labelled, text=text), IDENTIFIER)
    assert result.status == status
    assert len(result.authors) == len(result.candidates) == 2
    assert [candidate.author_positions for candidate in result.candidates] == [[1], [2]]
    assert all(candidate.association_status == "needs_review" for candidate in result.candidates)
    assert [len(author.affiliations) for author in result.authors] == affiliations
    assert result.reasons == (["unsupported_affiliation"] if status == "partial" else [])
    assert [author.corresponding for author in result.authors] == (
        [True, None] if reference == "cor" else [None, None]
    )
