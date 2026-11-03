"""Fixed structural counters only; called on admitted bytes inside the XML guest.

No association rule is changed. This is not a source authorization or a proof of
accuracy. All unsupported inputs raise; no partial counters escape.
"""

from typing import Annotated, Literal

from pydantic import Field

from emailmonitor.extraction import sciencedirect as xml
from emailmonitor.parsing.xml_protocol import XmlExpectation
from emailmonitor.sources.sciencedirect import Contract

MAX_OUTPUT = 4096
Counter = Annotated[int, Field(strict=True, ge=0, le=xml.MAX_NODES)]


class AffiliationDiagnostic(Contract):
    profile: Literal["private-affiliation-counters-v1"] = "private-affiliation-counters-v1"
    group_count: Counter
    author_count: Counter
    affiliation_count: Counter
    affiliations_with_direct_textfn: Counter
    labelled_affiliation_count: Counter
    author_affiliation_reference_count: Counter
    author_correspondence_reference_count: Counter
    author_footnote_reference_count: Counter
    authors_without_selected_affiliation: Counter
    groups_implicit_disabled_by_reference: Counter
    groups_implicit_disabled_by_label: Counter
    selected_affiliations_missing_textfn: Counter


def diagnose(data: bytes, expected: XmlExpectation) -> AffiliationDiagnostic:
    expected = XmlExpectation.model_validate(expected.model_dump())
    expected.check_bytes(data)
    observed = xml.parse_article(data, expected.requested_identifier)
    expected.check_observation(observed)
    if observed.status == "unsupported":
        raise ValueError("Unsupported diagnostic input")
    head = xml._head(xml._tree(data), expected.requested_identifier)
    counts = {name: 0 for name in AffiliationDiagnostic.model_fields if name != "profile"}
    for group in head.named("ce:author-group"):
        people = [
            child
            for child in group.children
            if child.tag in {xml._tag("ce:author"), xml._tag("ce:collaboration")}
        ]
        affiliations = group.named("ce:affiliation")
        targets = {
            child.attrs["id"]: child
            for child in group.children
            if "id" in child.attrs
            and child.tag
            in {xml._tag("ce:affiliation"), xml._tag("ce:correspondence"), xml._tag("ce:footnote")}
        }
        references = {person: xml._references(person, targets) for person in people}
        referenced = any(references.values())
        labelled = any(aff.named("ce:label") for aff in affiliations)
        counts["group_count"] += 1
        counts["author_count"] += len(people)
        counts["affiliation_count"] += len(affiliations)
        counts["affiliations_with_direct_textfn"] += sum(
            bool(aff.named("ce:textfn")) for aff in affiliations
        )
        counts["labelled_affiliation_count"] += sum(
            bool(aff.named("ce:label")) for aff in affiliations
        )
        counts["groups_implicit_disabled_by_reference"] += int(referenced)
        counts["groups_implicit_disabled_by_label"] += int(labelled)
        for person in people:
            for _, target in references[person]:
                for category in ("affiliation", "correspondence", "footnote"):
                    if target.tag == xml._tag("ce:" + category):
                        counts["author_" + category + "_reference_count"] += 1
            selected = [
                target
                for _, target in references[person]
                if target.tag == xml._tag("ce:affiliation")
            ]
            if not referenced and not labelled:
                selected = affiliations
            counts["authors_without_selected_affiliation"] += int(not selected)
            counts["selected_affiliations_missing_textfn"] += sum(
                not aff.named("ce:textfn") for aff in selected
            )
    return AffiliationDiagnostic.model_validate(counts)


def encode_output(result: AffiliationDiagnostic) -> bytes:
    result = AffiliationDiagnostic.model_validate(result.model_dump())
    output = result.model_dump_json().encode("ascii") + b"\n"
    if len(output) > MAX_OUTPUT:
        raise ValueError("Bounded diagnostic output required")
    return output


def decode_output(output: bytes) -> AffiliationDiagnostic:
    if type(output) is not bytes or not 0 < len(output) <= MAX_OUTPUT:
        raise ValueError("Bounded diagnostic output required")
    result = AffiliationDiagnostic.model_validate_json(output)
    # Exact canonical bytes reject duplicate fields, nonfinite values, omissions,
    # extra whitespace/trailing data and alternate numeric encodings.
    if encode_output(result) != output:
        raise ValueError("Canonical diagnostic output required")
    return result
