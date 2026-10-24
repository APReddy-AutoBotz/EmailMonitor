"""Pure syntax, legacy identity and candidate semantics; no SQL acceptance claims."""

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from emailmonitor.extraction.pdf import PdfLimits
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.results.cursor import decode, encode, fingerprint
from emailmonitor.results.models import ExportInput, ExportSnapshot, Filters
from emailmonitor.results.presence import observation_presence
from jsonschema import Draft202012Validator, FormatChecker
from pdf_fixture_builder import document
from pydantic import ValidationError
from test_html_extraction import parse as extract
from test_pdf_extraction import parse
from test_result_serialization import ITEM, JOB, snapshot
from test_xml_pipeline import retained

ROOT = Path(__file__).resolve().parents[3]
PRESENCE = ("all", "observed_candidate", "completed_without_candidate", "unresolved")


def test_default_filter_bytes_and_request_identity_remain_legacy_exact() -> None:
    expected = '{"job_id":null,"states":["accepted"],"author_target":"all","query":""}'
    assert Filters().model_dump_json() == expected
    assert Filters(item_id=None, article_outcome_presence="all").model_dump_json() == expected
    assert fingerprint(Filters()) == hashlib.sha256(expected.encode()).hexdigest()
    request = ExportInput(format="csv", purpose="academic_contact_research")
    legacy = request.model_dump_json()
    assert "item_id" not in legacy and "article_outcome_presence" not in legacy
    assert ExportInput.model_validate_json(legacy).model_dump_json() == legacy
    old_snapshot = snapshot().model_dump(mode="json")
    old_snapshot.pop("article_filter_bindings", None)
    assert (
        ExportSnapshot.model_validate_json(json.dumps(old_snapshot)).article_filter_bindings == ()
    )


@pytest.mark.parametrize("presence", PRESENCE)
def test_filter_and_export_schema_selection_parity(presence: str) -> None:
    document = {
        "job_id": str(JOB),
        "item_id": str(ITEM),
        "format": "xlsx",
        "purpose": "academic_contact_research",
        "article_outcome_presence": presence,
    }
    schema = json.loads((ROOT / "contracts/export-request.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    request = ExportInput.model_validate(document)
    assert request.filters().item_id == ITEM
    assert request.filters().article_outcome_presence == presence
    assert request.filters().states == ("accepted",)


@pytest.mark.parametrize(
    "changes",
    [
        {"item_id": str(ITEM)},
        {"job_id": None, "item_id": str(ITEM)},
        {"job_id": str(JOB), "item_id": "bad"},
        {"article_outcome_presence": "no_email"},
        {"article_outcome_presence": None},
    ],
)
def test_unsafe_selector_schema_and_models_refuse(changes: dict[str, object]) -> None:
    document = {"format": "csv", "purpose": "academic_contact_research", **changes}
    schema = json.loads((ROOT / "contracts/export-request.schema.json").read_text())
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document))
    with pytest.raises(ValidationError):
        ExportInput.model_validate(document)
    with pytest.raises(ValidationError):
        Filters.model_validate_json(json.dumps(changes))


@pytest.mark.parametrize(
    "field", ["tenant", "dataset", "job", "item", "query", "states", "target", *PRESENCE]
)
def test_complete_cursor_filter_mismatch_refuses(field: str) -> None:
    org = uuid4()
    initial = Filters(job_id=JOB, item_id=ITEM, article_outcome_presence="observed_candidate")
    cursor = encode(org, "outcomes", initial, JOB, ITEM)
    altered = initial.model_dump(mode="json")
    kind = "outcomes"
    if field == "tenant":
        org = uuid4()
    elif field == "dataset":
        kind = "contacts"
    elif field in {"job", "item"}:
        altered[field + "_id"] = str(uuid4())
    elif field in PRESENCE:
        altered["article_outcome_presence"] = field
        if field == "observed_candidate":
            altered.pop("item_id")
    elif field == "target":
        altered["author_target"] = "first"
    elif field == "states":
        altered["states"] = ["needs_review"]
    else:
        altered["query"] = "changed"
    with pytest.raises(ValueError):
        decode(org, kind, Filters.model_validate_json(json.dumps(altered)), cursor)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("article-a.html", "observed_candidate"),
        ("no-contact.html", "completed_without_candidate"),
        ("tooltip.html", "unresolved"),
    ],
)
def test_html_candidate_presence_is_not_execution_or_contact_count(
    name: str, expected: str
) -> None:
    assert observation_presence(extract(name)) == expected


@pytest.mark.parametrize(
    "status,candidates,expected",
    [
        ("observed", True, "observed_candidate"),
        ("partial", True, "observed_candidate"),
        ("partial", False, "unresolved"),
        ("no_contact", False, "completed_without_candidate"),
        ("unsupported", False, "unresolved"),
    ],
)
def test_xml_empty_partial_is_never_negative(status: str, candidates: bool, expected: str) -> None:
    document = retained().model_dump(mode="json")
    document["status"] = status
    document["reasons"] = (
        ["unsupported_affiliation"] if status in {"partial", "unsupported"} else []
    )
    if not candidates:
        document["candidates"] = []
    if status == "unsupported":
        document["authors"] = []
        document["excerpts_retained"] = False
    assert observation_presence(RetainedXml.model_validate_json(json.dumps(document))) == expected


def test_pdf_conceptual_complete_negative_and_partial_candidates_have_no_durable_route() -> None:
    assert observation_presence(parse("no-contact.pdf")) == "completed_without_candidate"
    assert (
        observation_presence(
            parse(
                "article-a.pdf",
                document(
                    [
                        [
                            (50, 715, 11, "Authors: Alex Chen [1]"),
                            (50, 680, 11, "1 Synthetic Institute"),
                            (50, 130, 11, "Correspondence [1]: Alex Chen; alex.chen@example.org"),
                        ],
                        [(50, 715, 11, "Additional article text")],
                    ]
                ),
                limits=PdfLimits(max_pages=1),
            )
        )
        == "observed_candidate"
    )
    assert (
        observation_presence(parse("article-a.pdf", limits=PdfLimits(max_pages=1))) == "unresolved"
    )
    assert observation_presence(parse("scanned.pdf")) == "unresolved"
    sql = (
        ROOT / "services/backend/migrations/versions/0016_retained_article_filters.sql"
    ).read_text()
    assert "route='pdf'" not in sql and "fetch_pdf" not in sql


def test_filtered_snapshot_requires_exact_binding_and_keeps_outcome_shape() -> None:
    before = snapshot()
    data = before.model_dump(mode="json")
    data["filters"]["item_id"] = str(ITEM)
    data["filters"]["article_outcome_presence"] = "unresolved"
    with pytest.raises(ValidationError):
        ExportSnapshot.model_validate_json(json.dumps(data))
    data["article_filter_bindings"] = [
        {"job_id": str(JOB), "item_id": str(ITEM), "fingerprint": "a" * 64}
    ]
    current = ExportSnapshot.model_validate_json(json.dumps(data))
    assert current.article_outcomes == before.article_outcomes
    data["article_filter_bindings"][0]["item_id"] = str(UUID(int=999))
    with pytest.raises(ValidationError):
        ExportSnapshot.model_validate_json(json.dumps(data))


def test_candidate_syntax_and_unmatched_identity_never_make_a_negative() -> None:
    value = extract("article-a.html")
    assert value.candidates
    candidate = value.candidates[0].model_dump(mode="json")
    # The classifier sees retained candidate facts, not Contact acceptance.
    candidate["association_status"] = "unmatched"
    candidate["author_positions"] = []
    candidate["raw_address"] = "observed-but-invalid-address"
    document = value.model_dump(mode="json")
    document["candidates"][0] = candidate
    assert (
        observation_presence(type(value).model_validate_json(json.dumps(document)))
        == "observed_candidate"
    )


def test_filtered_snapshot_rejects_duplicate_and_extra_binding_identity() -> None:
    data = snapshot().model_dump(mode="json")
    data["filters"]["item_id"] = str(ITEM)
    binding = {"job_id": str(JOB), "item_id": str(ITEM), "fingerprint": "a" * 64}
    for bindings in ([binding, binding], [binding, {**binding, "item_id": str(uuid4())}]):
        data["article_filter_bindings"] = bindings
        with pytest.raises(ValidationError):
            ExportSnapshot.model_validate_json(json.dumps(data))


def test_migration_keeps_legacy_entrypoints_wrappers_and_private_authority() -> None:
    import re

    sql = (
        ROOT / "services/backend/migrations/versions/0016_retained_article_filters.sql"
    ).read_text()
    names = re.findall(r"CREATE(?: OR REPLACE)? FUNCTION emailmonitor\.(\w+)\(", sql)
    assert "result_outcomes" not in names and "result_outcome_document" not in names
    assert "service_batch_visible" not in names and "service_job_visible" not in names
    assert "exports_create" not in names and "exports_preview" not in names
    assert "exports_create_pre_entitlement" in names and "exports_preview_pre_entitlement" in names
    grants = re.findall(r"GRANT .*?;", sql, re.S)
    assert grants == [
        "GRANT EXECUTE ON FUNCTION "
        "emailmonitor.result_outcomes_filtered(uuid,jsonb,uuid,uuid,integer) "
        "TO emailmonitor_runtime;"
    ]
    assert (
        "FROM PUBLIC,emailmonitor_runtime,emailmonitor_authenticator,"
        "emailmonitor_worker,emailmonitor_publisher;" in sql
    )
    assert "COALESCE(i.inherited_job_id,i.job_id)" not in sql
    assert "cardinality(l.visited)<1000" in sql
    assert "jsonb_array_elements(e.snapshot->'article_filter_bindings')" in sql
    assert "emailmonitor.work_export_allowed(p_org,p_export)" in sql
    assert "min(version_num)='0016_retained_article_filters'" in sql
    body = sql.split("CREATE FUNCTION emailmonitor.result_outcomes_filtered", 1)[1].split(
        "END $$;", 1
    )[0]
    assert body.index("->>'presence'=presence") < body.index("ORDER BY i.job_id,i.id LIMIT p_limit")
    assert "RETURN QUERY SELECT * FROM emailmonitor.result_outcomes(" in body
