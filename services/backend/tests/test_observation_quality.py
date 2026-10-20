"""Authored retained-fact view tests; no source acquisition or parser policy change."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.models import Bundle, Review
from emailmonitor.associations.quality import ObservationQuality, SourceBinding, project_quality
from emailmonitor.associations.review import apply_review
from emailmonitor.extraction.xml_retained import RetainedXml
from pydantic import ValidationError
from test_xml_pipeline import SETTINGS, retained

ORG, BATCH = UUID(int=1), UUID(int=44)
SOURCE = SourceBinding(UUID(int=2), 1, 1, 1)


def fixture() -> tuple[RetainedXml, Bundle]:
    value = retained().model_copy(
        update={"status": "partial", "reasons": ["unsupported_affiliation"]}
    )
    value = RetainedXml.model_validate_json(value.model_dump_json())
    return value, map_observation(SETTINGS, ORG, value)


def test_quality_stays_article_scoped_and_review_does_not_rewrite_it() -> None:
    value, bundle = fixture()
    before = bundle.model_dump_json()
    original = project_quality(ORG, BATCH, bundle, value.model_dump(mode="json"), SOURCE)
    assert original.reasons == ("unsupported_affiliation",)
    assert original.scope == "article"
    association = next(a for a in bundle.associations if a.author_id is not None)
    reviewed = apply_review(
        SETTINGS,
        bundle,
        Review(
            association_id=association.id,
            expected_revision=1,
            action="accept",
            author_id=association.author_id,
            evidence_ids=association.evidence_ids,
            reason="Authored evidence review",
        ),
    )
    assert project_quality(ORG, BATCH, reviewed, value.model_dump(mode="json"), SOURCE) == original
    assert bundle.model_dump_json() == before
    assert reviewed.authors == bundle.authors and reviewed.evidence == bundle.evidence
    payload = original.model_dump(mode="json")
    assert set(payload) == {
        "view_version",
        "organization_id",
        "batch_id",
        "scope",
        "parser_version",
        "observation_route",
        "observation_status",
        "reason_availability",
        "reasons",
        "review_scope",
    }
    assert "@" not in json.dumps(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_digest", "0" * 64),
        ("source_url", "https://example.org/changed"),
        ("parser_version", "future-version"),
        ("observation_status", "observed"),
        ("observation_route", "html"),
        ("organization_id", UUID(int=99)),
    ],
)
def test_batch_identity_mismatch_refuses(field: str, value: object) -> None:
    observed, bundle = fixture()
    with pytest.raises(ValueError):
        project_quality(
            ORG,
            BATCH,
            bundle.model_copy(update={field: value}),
            observed.model_dump(mode="json"),
            SOURCE,
        )


@pytest.mark.parametrize(
    "source",
    [
        SourceBinding(UUID(int=99), 1, 1, 1),
        SourceBinding(UUID(int=2), 2, 1, 1),
        SourceBinding(UUID(int=2), 1, 2, 1),
        SourceBinding(UUID(int=2), 1, 1, 2),
    ],
)
def test_retained_authority_binding_mismatch_refuses(source: SourceBinding) -> None:
    observed, bundle = fixture()
    with pytest.raises(ValueError):
        project_quality(ORG, BATCH, bundle, observed.model_dump(mode="json"), source)


@pytest.mark.parametrize(
    "change",
    [
        {"reasons": []},
        {"reasons": ["invented"]},
        {"reasons": ["unsupported_affiliation"] * 21},
        {"observation_status": "observed"},
        {"observation_status": "requires_browser"},
        {"reason_availability": "not_recorded"},
        {"parser_version": "elsevier-xml-head-v2"},
        {"observation_route": "html"},
        {"scope": "author"},
        {"author_id": str(UUID(int=8))},
        {"affiliations": ["Invented Institute"]},
        {"review_scope": "affiliation"},
    ],
)
def test_closed_quality_contract_refuses_unsupported_claims(change: dict[str, object]) -> None:
    observed, bundle = fixture()
    result = project_quality(ORG, BATCH, bundle, observed.model_dump(mode="json"), SOURCE)
    with pytest.raises(ValidationError):
        ObservationQuality.model_validate_json(
            json.dumps({**result.model_dump(mode="json"), **change})
        )


def test_existing_v1_bundle_roundtrip_bytes_and_replay_mapping_are_unchanged() -> None:
    observed, bundle = fixture()
    payload = bundle.model_dump_json()
    project_quality(ORG, BATCH, bundle, observed.model_dump(mode="json"), SOURCE)
    assert Bundle.model_validate_json(payload).model_dump_json() == payload
    assert map_observation(SETTINGS, ORG, observed).model_dump_json() == payload
    root = Path(__file__).resolve().parents[3]
    example = json.loads((root / "contracts/examples/association-bundle.json").read_text())
    assert Bundle.model_validate_json(json.dumps(example)).model_dump(mode="json") == example


def test_unknown_retained_route_or_extra_fields_refuse() -> None:
    observed, bundle = fixture()
    for change in (
        {"route": "unknown"},
        {"author_guess": "synthetic"},
        {"reasons": ["unbounded text"]},
    ):
        with pytest.raises(ValueError):
            project_quality(
                ORG, BATCH, bundle, {**observed.model_dump(mode="json"), **change}, SOURCE
            )


@pytest.mark.parametrize(
    "status,reasons",
    [
        ("no_contact", []),
        ("partial", ["unsupported_affiliation"]),
        ("unsupported", ["unsupported_structure"]),
    ],
)
def test_empty_contact_outcomes_still_have_direct_quality(status: str, reasons: list[str]) -> None:
    value = retained().model_dump(mode="json")
    value.update(status=status, reasons=reasons, candidates=[])
    if status == "unsupported":
        value["authors"] = []
    observed = RetainedXml.model_validate_json(json.dumps(value))
    bundle = map_observation(SETTINGS, ORG, observed)
    assert not bundle.candidates
    quality = project_quality(ORG, BATCH, bundle, value, SOURCE)
    assert quality.observation_status == status and quality.reasons == tuple(reasons)


def test_committed_quality_schema_and_example_match_runtime() -> None:
    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "contracts/observation-quality.schema.json").read_text())
    expected = ObservationQuality.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert schema == expected
    example = json.loads((root / "contracts/examples/observation-quality.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    assert (
        ObservationQuality.model_validate_json(json.dumps(example)).model_dump(mode="json")
        == example
    )
