"""Retained metadata projection; no live acquisition or new publication semantics."""

from uuid import UUID

import pytest
from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.metadata import project_metadata
from emailmonitor.associations.quality import SourceBinding
from emailmonitor.extraction.html import MetadataValues
from test_html_extraction import SETTINGS, parse, payload
from test_xml_pipeline import retained

ORG, BATCH = UUID(int=1), UUID(int=44)
SOURCE = SourceBinding(UUID(int=2), 1, 1, 1)


def test_exact_preferred_values_and_all_citations_are_preserved() -> None:
    value = parse("article-a.html")
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert result.preferred_metadata == value.preferred_metadata
    assert result.facts == tuple(value.metadata)
    assert result.source_url == value.url and result.content_digest == value.content_digest
    assert result.date_interpretation == "retained_text_and_recorded_type_only"


def test_multiple_values_preserve_precedence_without_erasing_other_observations() -> None:
    data = payload("article-a.html").replace(
        b"</head>",
        b'<meta name="citation_journal_title" content="Another authored journal"></head>',
    )
    value = parse("article-a.html", data)
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert "journal" in result.multiple_value_fields
    assert result.preferred_metadata == value.preferred_metadata
    assert [f.value for f in result.facts if f.field == "journal"] == [
        f.value for f in value.metadata if f.field == "journal"
    ]


def test_xml_unrecorded_metadata_is_not_filled_from_identifiers_or_contact_evidence() -> None:
    value = retained()
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert result.fact_availability == "not_recorded"
    assert result.preferred_metadata == MetadataValues() and result.facts == ()


@pytest.mark.parametrize("mutation", ["organization", "snapshot", "digest", "url"])
def test_mismatched_retained_binding_refuses(mutation: str) -> None:
    value = parse("article-a.html")
    bundle = map_observation(SETTINGS, ORG, value)
    document = value.model_dump(mode="json")
    if mutation == "organization":
        bundle = bundle.model_copy(update={"organization_id": UUID(int=99)})
    elif mutation == "snapshot":
        bundle = bundle.model_copy(update={"preferred_metadata": MetadataValues(title="different")})
    elif mutation == "digest":
        document["content_digest"] = "0" * 64
    else:
        document["url"] = value.url.replace("article-a", "article-b")
    with pytest.raises(ValueError):
        project_metadata(ORG, BATCH, bundle, document, SOURCE)


def test_pdf_keeps_page_region_evidence_and_unspecified_date_type() -> None:
    from emailmonitor.extraction.pdf_retained import PdfBinding, retain_pdf
    from test_pdf_extraction import parse as parse_pdf

    value = retain_pdf(
        parse_pdf("article-a.pdf"),
        PdfBinding(
            organization=ORG,
            job=SOURCE.job,
            item=UUID(int=3),
            generation=1,
            deletion_generation=1,
            policy_version=1,
            discovery_revision=1,
        ),
        permit_excerpts=True,
    )
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert result.facts == tuple(value.metadata)
    assert result.facts and all(f.date_type == "unspecified" for f in result.facts)
    assert all(getattr(f.evidence, "page", 0) >= 1 for f in result.facts)


def test_committed_metadata_schema_example_and_runtime_agree() -> None:
    import json
    from pathlib import Path

    from emailmonitor.associations.metadata import ArticleMetadata
    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "contracts/article-metadata.schema.json").read_text())
    expected = ArticleMetadata.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert schema == expected
    document = json.loads((root / "contracts/examples/article-metadata.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    assert (
        ArticleMetadata.model_validate_json(json.dumps(document)).model_dump(mode="json")
        == document
    )
