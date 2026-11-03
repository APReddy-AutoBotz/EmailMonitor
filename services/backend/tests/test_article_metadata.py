"""Retained metadata projection; no live acquisition or new publication semantics."""

from uuid import UUID

import pytest
from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.metadata import project_metadata, project_metadata_precision
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
    date_index = next(i for i, fact in enumerate(result.facts) if fact.field == "publication_date")
    annotation = project_metadata_precision(result).date_precisions[0]
    assert annotation.fact_index == date_index
    assert annotation.precision == "day"
    assert result.facts[date_index].value == "2026-01-15"
    assert result.facts[date_index].evidence == value.metadata[date_index].evidence


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


@pytest.mark.parametrize(
    ("supplied", "precision"),
    [("2026", "year"), ("2026-02", "month"), ("2024-02-29", "day"), ("2026-02-29", "unrecognized")],
)
def test_authored_source_date_retains_exact_citation_and_precision(
    supplied: str, precision: str
) -> None:
    data = payload("article-a.html").replace(
        b' datetime="2026-01-15"', f' datetime="{supplied}"'.encode()
    )
    value = parse("article-a.html", data)
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    annotation = project_metadata_precision(result).date_precisions[0]
    fact = result.facts[annotation.fact_index]
    assert annotation.precision == precision and fact.value == supplied
    assert fact.evidence == value.metadata[annotation.fact_index].evidence


def test_conflicting_date_facts_remain_separate_and_cited() -> None:
    data = payload("article-a.html").replace(
        b"</main>", b'<time datetime="2026-02">February 2026</time></main>'
    )
    value = parse("article-a.html", data)
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert "publication_date" in result.multiple_value_fields
    annotations = project_metadata_precision(result).date_precisions
    assert [(result.facts[row.fact_index].value, row.precision) for row in annotations] == [
        ("2026-01-15", "day"),
        ("2026-02", "month"),
    ]
    assert (
        result.facts[annotations[0].fact_index].evidence.locator
        != result.facts[annotations[1].fact_index].evidence.locator
    )


def test_xml_unrecorded_metadata_is_not_filled_from_identifiers_or_contact_evidence() -> None:
    value = retained()
    bundle = map_observation(SETTINGS, ORG, value)
    result = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert result.fact_availability == "not_recorded"
    assert result.preferred_metadata == MetadataValues() and result.facts == ()
    assert project_metadata_precision(result).date_precisions == ()


@pytest.mark.parametrize("mutation", ["wrong_index", "wrong_precision", "duplicate"])
def test_precision_annotation_refuses_mismatch_and_does_not_change_source_text(
    mutation: str,
) -> None:
    from emailmonitor.associations.metadata import ArticleMetadataPrecision

    value = parse("article-a.html")
    bundle = map_observation(SETTINGS, ORG, value)
    original = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    document = project_metadata_precision(original).model_dump(mode="json")
    rows = document["date_precisions"]
    if mutation == "wrong_index":
        rows[0]["fact_index"] = 0
    elif mutation == "wrong_precision":
        rows[0]["precision"] = "year"
    else:
        rows.append(rows[0].copy())
    with pytest.raises(ValueError):
        ArticleMetadataPrecision.model_validate(document)
    assert original.facts == tuple(value.metadata)


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


def test_precision_schema_and_example_preserve_the_original_metadata_contract() -> None:
    import json
    from pathlib import Path

    from emailmonitor.associations.metadata import ArticleMetadataPrecision
    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "contracts/article-metadata-precision.schema.json").read_text())
    expected = ArticleMetadataPrecision.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert schema == expected
    document = json.loads((root / "contracts/examples/article-metadata-precision.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    assert (
        ArticleMetadataPrecision.model_validate_json(json.dumps(document)).model_dump(mode="json")
        == document
    )
    assert document["metadata"] == json.loads(
        (root / "contracts/examples/article-metadata.json").read_text()
    )


def test_precision_route_uses_the_existing_metadata_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast

    import emailmonitor.associations.api as api
    from emailmonitor.organizations.database import Database
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    value = parse("article-a.html")
    bundle = map_observation(SETTINGS, ORG, value)
    expected = project_metadata(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    calls: list[tuple[str, UUID, UUID]] = []

    class SyntheticAssociations:
        def __init__(self, _database: Database, session: str, _settings: object) -> None:
            self.session = session

        def metadata(self, org: UUID, batch: UUID) -> object:
            calls.append((self.session, org, batch))
            if org != ORG or batch != BATCH:
                raise HTTPException(404, "Resource unavailable")
            return expected

    monkeypatch.setattr(api, "Associations", SyntheticAssociations)
    app = FastAPI()
    app.include_router(
        api.association_router(
            cast(Database, object()), lambda _: "synthetic", lambda _: "synthetic", SETTINGS
        )
    )
    url = f"/organizations/{ORG}/association-batches/{BATCH}/article-metadata"
    with TestClient(app) as client:
        old = client.get(url)
        new = client.get(url + "/precision")
        assert old.status_code == new.status_code == 200
        assert old.json() == expected.model_dump(mode="json")
        assert new.json()["metadata"] == old.json()
        assert new.json()["date_precisions"][0]["precision"] == "day"
        assert (
            client.get(url.replace(str(ORG), str(UUID(int=99))) + "/precision").status_code == 404
        )
    assert calls == [
        ("synthetic", ORG, BATCH),
        ("synthetic", ORG, BATCH),
        ("synthetic", UUID(int=99), BATCH),
    ]
