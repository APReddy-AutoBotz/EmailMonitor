"""Real CSV/XML/ZIP bytes from synthetic observed facts, without acquisition or formulas."""

import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from emailmonitor.associations.models import Bundle
from emailmonitor.results.models import ArticleOutcome, Contact, ExportSnapshot, Filters
from emailmonitor.results.render import RenderDenied, render, safe_csv, worksheet
from pydantic import ValidationError
from test_associations import ORG, html

NOW = datetime(2026, 10, 13, tzinfo=UTC)
JOB = UUID("b0000000-0000-4000-8000-000000000001")
BATCH = UUID("b0000000-0000-4000-8000-000000000002")
EXPORT = UUID("b0000000-0000-4000-8000-000000000003")
ACTOR = UUID("b0000000-0000-4000-8000-000000000004")
ITEM = UUID("b0000000-0000-4000-8000-000000000005")


def contact(title: str | None = None, bundle: Bundle | None = None) -> Contact:
    if bundle is None:
        bundle = html("article-a.html")
    association = next(value for value in bundle.associations if value.state == "accepted")
    assert association.state == "accepted"
    author = next(value for value in bundle.authors if value.id == association.author_id)
    candidate = next(value for value in bundle.candidates if value.id == association.candidate_id)
    return Contact(
        organization_id=ORG,
        job_id=JOB,
        batch_id=BATCH,
        association_id=association.id,
        revision=association.revision,
        candidate_id=candidate.id,
        author_id=author.id,
        author_name=author.display_name,
        first_author=author.first,
        corresponding_author=author.corresponding,
        affiliations=author.affiliations,
        raw_address=candidate.address.raw_address,
        normalized_address=candidate.address.normalized_address,
        syntax_status=candidate.address.syntax_status,
        state=association.state,
        evidence_strength=association.evidence_strength,
        association_reason=association.reason,
        evidence_ids=association.evidence_ids,
        source_url=bundle.source_url,
        policy_version=1,
        title=title if title is not None else bundle.preferred_metadata.title,
        observed_at=NOW,
    )


def snapshot(
    *, format: str = "csv", title: str | None = None, outcomes: bool = True
) -> ExportSnapshot:
    payload: dict[str, object] = {
        "organization_id": ORG,
        "export_id": EXPORT,
        "requested_by": ACTOR,
        "purpose": "academic_contact_research",
        "filters": Filters(job_id=JOB),
        "format": format,
        "include_article_outcomes": outcomes,
        "contacts": (contact(title),),
        "article_outcomes": (
            ArticleOutcome(
                organization_id=ORG,
                job_id=JOB,
                item_id=ITEM,
                source_url="https://synthetic.publisher.example/no-contact.html",
                state="no_contact",
                reason="no_contact",
                batch_id=None,
                completed_at=NOW,
                inherited_job_id=None,
                observation_status="no_contact",
            ),
        )
        if outcomes
        else (),
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    return ExportSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        "+2",
        "-2",
        "@SUM(A1)",
        "  =SUM(A1)",
        "\t=2",
        "\r=2",
        "\n=2",
        "＝1+1",
        "＋2",
        "－2",
        "＠SUM(A1)",
        "\u00a0=2",
        "name\n=2",
        "name\x00value",
        "name\u2028=2",
        '=";=SUM(A1)',
    ],
)
def test_csv_formula_and_control_input_refuses_without_changing_original(value: str) -> None:
    with pytest.raises(RenderDenied) as error:
        safe_csv(value)
    assert error.value.reason == "unsafe_csv_cell"


@pytest.mark.parametrize(
    "value", ["Mira Rao", "élise@example.org", 'normal,semicolon;"quoted"', "研究者"]
)
def test_safe_csv_preserves_observed_text(value: str) -> None:
    assert safe_csv(value) == value


def test_real_csv_zip_has_distinct_contacts_outcomes_and_use_state() -> None:
    artifact = render(snapshot())
    assert artifact.extension == "zip" and artifact.content_type == "application/zip"
    with ZipFile(io.BytesIO(artifact.body)) as archive:
        assert set(archive.namelist()) == {"contacts.csv", "article-outcomes.csv", "readme.txt"}
        contacts = list(csv.reader(io.StringIO(archive.read("contacts.csv").decode())))
        outcomes = list(csv.reader(io.StringIO(archive.read("article-outcomes.csv").decode())))
        assert len(contacts) == len(outcomes) == 2
        assert len(contacts[0]) == len(contacts[1])
        assert contacts[1][contacts[0].index("Observed address")] == contact().raw_address
        assert contacts[1][contacts[0].index("Association state")] == "accepted"
        assert outcomes[1][outcomes[0].index("Processing state")] == "no_contact"
        assert "no mailbox validation or outreach approval" in archive.read("readme.txt").decode()
        assert "no_contact" not in contacts[1]


def test_contacts_only_is_plain_csv() -> None:
    artifact = render(snapshot(outcomes=False))
    assert artifact.extension == "csv" and artifact.content_type == "text/csv; charset=utf-8"
    assert artifact.body.startswith(b'"Association ID"')


def test_reuse_provenance_exports_without_changing_legacy_rows() -> None:
    from emailmonitor.results.render import contact_rows, outcome_rows

    original = snapshot()
    assert "Observation origin" not in contact_rows(original)[0]
    assert "Observation origin" not in outcome_rows(original)[0]
    original_contact = original.contacts[0]
    reused_contact = Contact.model_validate(
        {
            **original_contact.model_dump(),
            "observation_origin": "reused",
            "observed_at": NOW - timedelta(hours=1),
        }
    )
    original_outcome = original.article_outcomes[0]
    reused_outcome = ArticleOutcome.model_validate(
        {
            **original_outcome.model_dump(),
            "observation_origin": "reused",
            "observed_at": NOW - timedelta(hours=1),
        }
    )
    updated = original.model_copy(
        update={"contacts": (reused_contact,), "article_outcomes": (reused_outcome,)}
    )
    contacts = contact_rows(updated)
    outcomes = outcome_rows(updated)
    assert contacts[1][contacts[0].index("Observation origin")] == "Reused"
    assert contacts[1][contacts[0].index("Observed at")] == (NOW - timedelta(hours=1)).isoformat()
    assert contacts[1][contacts[0].index("Observation age at snapshot (seconds)")] == "3600"
    assert outcomes[1][outcomes[0].index("Observation origin")] == "Reused"
    assert (
        outcomes[1][outcomes[0].index("Original observation time")]
        == (NOW - timedelta(hours=1)).isoformat()
    )
    assert outcomes[1][outcomes[0].index("Observation age at snapshot (seconds)")] == "3600"
    assert "observation_origin" not in original_contact.model_dump(mode="json")
    assert "observation_origin" not in original_outcome.model_dump(mode="json")
    assert "observed_at" not in original_outcome.model_dump(mode="json")


def test_reused_outcome_requires_original_aware_time() -> None:
    original = snapshot().article_outcomes[0].model_dump()
    with pytest.raises(ValidationError):
        ArticleOutcome.model_validate({**original, "observation_origin": "reused"})
    with pytest.raises(ValidationError):
        ArticleOutcome.model_validate(
            {**original, "observation_origin": "reused", "observed_at": NOW.replace(tzinfo=None)}
        )


def test_reused_outcome_schema_and_runtime_refuse_incomplete_provenance() -> None:
    import json
    from pathlib import Path

    import jsonschema

    schema = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/result-outcomes.schema.json").read_text()
    )
    original = snapshot().article_outcomes[0].model_dump(mode="json")
    valid = {**original, "observation_origin": "reused", "observed_at": NOW.isoformat()}
    schema_value = {"items": [valid], "next_cursor": None}
    jsonschema.validate(schema_value, schema, format_checker=jsonschema.FormatChecker())
    assert ArticleOutcome.model_validate_json(json.dumps(valid)).observation_origin == "reused"
    del valid["observed_at"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"items": [valid], "next_cursor": None}, schema)
    with pytest.raises(ValidationError):
        ArticleOutcome.model_validate_json(json.dumps(valid))


def test_reused_future_time_does_not_invent_export_age() -> None:
    from emailmonitor.results.render import contact_rows

    original = snapshot()
    reused = Contact.model_validate(
        {
            **original.contacts[0].model_dump(),
            "observation_origin": "reused",
            "observed_at": NOW + timedelta(seconds=1),
        }
    )
    rows = contact_rows(original.model_copy(update={"contacts": (reused,)}))
    assert rows[1][rows[0].index("Observation age at snapshot (seconds)")] == ""


def test_reuse_provenance_is_in_actual_csv_and_xlsx_bytes() -> None:
    for format in ("csv", "xlsx"):
        original = snapshot(format=format)
        reused_contact = Contact.model_validate(
            {
                **original.contacts[0].model_dump(),
                "observation_origin": "reused",
                "observed_at": NOW - timedelta(hours=1),
            }
        )
        reused_outcome = ArticleOutcome.model_validate(
            {
                **original.article_outcomes[0].model_dump(),
                "observation_origin": "reused",
                "observed_at": NOW - timedelta(hours=1),
            }
        )
        updated = original.model_copy(
            update={"contacts": (reused_contact,), "article_outcomes": (reused_outcome,)}
        )
        artifact = render(updated)
        with ZipFile(io.BytesIO(artifact.body)) as archive:
            if format == "csv":
                contacts = archive.read("contacts.csv").decode()
                outcomes = archive.read("article-outcomes.csv").decode()
            else:
                contacts = archive.read("xl/worksheets/sheet1.xml").decode()
                outcomes = archive.read("xl/worksheets/sheet2.xml").decode()
        assert "Observation origin" in contacts and "Reused" in contacts and "3600" in contacts
        assert (
            "Original observation time" in outcomes and "Reused" in outcomes and "3600" in outcomes
        )


@pytest.mark.parametrize(
    "value", ["=1+1", '＝HYPERLINK("https://example.org")', '<f>bad</f> & "text"', "研究者"]
)
def test_actual_xlsx_is_literal_text_without_external_or_formula_parts(value: str) -> None:
    artifact = render(snapshot(format="xlsx", title=value))
    assert artifact.extension == "xlsx"
    with ZipFile(io.BytesIO(artifact.body)) as archive:
        assert set(archive.namelist()) == {
            "[Content_Types].xml",
            "_rels/.rels",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/worksheets/sheet1.xml",
            "xl/worksheets/sheet2.xml",
            "xl/worksheets/sheet3.xml",
        }
        roots = [ET.fromstring(archive.read(name)) for name in archive.namelist()]
        assert not any(
            node.tag.split("}")[-1] in {"f", "externalLink", "hyperlink"}
            for root in roots
            for node in root.iter()
        )
        assert not any(
            node.get("TargetMode") == "External" for root in roots for node in root.iter()
        )
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        texts = [node.text for node in sheet.iter() if node.tag.endswith("}t")]
        assert value in texts
        assert all(node.get("t") == "inlineStr" for node in sheet.iter() if node.tag.endswith("}c"))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        assert [node.get("name") for node in workbook.iter() if node.tag.endswith("}sheet")] == [
            "Contacts",
            "Article outcomes",
            "Readme",
        ]


def test_csv_dangerous_observed_title_refuses_whole_artifact() -> None:
    with pytest.raises(RenderDenied, match="unsafe_csv_cell"):
        render(snapshot(title='=HYPERLINK("https://example.org")'))


@pytest.mark.parametrize("value", ["bad\x00text", "bad\ud800text", "x" * 32768])
def test_xlsx_invalid_xml_or_oversized_cell_refuses(value: str) -> None:
    with pytest.raises(RenderDenied, match="unsupported_text"):
        worksheet([[value]])


def test_render_caps_input_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("emailmonitor.results.render.MAX_INPUT", 1)
    with pytest.raises(RenderDenied, match="render_limit"):
        render(snapshot())
    monkeypatch.setattr("emailmonitor.results.render.MAX_INPUT", 2 * 1024 * 1024)
    monkeypatch.setattr("emailmonitor.results.render.MAX_OUTPUT", 1)
    with pytest.raises(RenderDenied, match="render_limit"):
        render(snapshot())


def test_snapshot_rejects_cross_tenant_rejected_and_unrequested_data() -> None:
    original = snapshot()
    for changes in (
        {"organization_id": ACTOR},
        {"include_article_outcomes": False},
        {"contacts": (contact().model_copy(update={"state": "rejected"}),)},
        {"contacts": (contact(), contact())},
        {"expires_at": NOW},
    ):
        payload = original.model_dump()
        payload.update(changes)
        with pytest.raises(ValidationError):
            ExportSnapshot.model_validate(payload)


def test_reviewed_first_author_mapping_does_not_invent_correspondence_role() -> None:
    from emailmonitor.associations.review import apply_review
    from test_association_review import request
    from test_associations import SETTINGS

    bundle = html("article-a.html")
    cited = tuple(
        dict.fromkeys((*bundle.candidates[0].evidence_ids, *bundle.authors[0].evidence_ids))
    )
    reviewed = apply_review(
        SETTINGS,
        bundle,
        request(action="correct", author_id=bundle.authors[0].id, evidence_ids=cited),
    )
    result = contact(bundle=reviewed)
    assert result.state == "accepted" and result.first_author is True
    assert result.corresponding_author is None and result.association_reason == "reviewed_evidence"
    assert result.raw_address == bundle.candidates[0].address.raw_address
    assert result.delivery_status == "unverified" and result.outreach_eligibility == "not_assessed"


def test_opc_default_namespaces_are_compatible_and_cells_remain_literal() -> None:
    # Actual installed consumer previously rejected prefixed OPC roots. Keep this
    # packaging regression alongside XML-level formula refusal, without a runtime dependency.
    artifact = render(snapshot(format="xlsx", title="=1+1"))
    with ZipFile(io.BytesIO(artifact.body)) as archive:
        types = archive.read("[Content_Types].xml")
        relationships = archive.read("_rels/.rels")
        assert (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"' in types
        )
        assert (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
            in relationships
        )
        assert b"ns0:" not in types and b"ns0:" not in relationships
        for name in archive.namelist():
            if name.startswith("xl/worksheets/"):
                assert b"<f" not in archive.read(name)


@pytest.mark.parametrize("control", [chr(code) for code in range(0x80, 0xA0)])
def test_all_c1_csv_controls_refuse_at_leading_and_embedded_positions(control: str) -> None:
    for value in (control + "=1+1", control + "ordinary text", "ordinary" + control + "text"):
        with pytest.raises(RenderDenied, match="unsafe_csv_cell"):
            safe_csv(value)


@pytest.mark.parametrize("control", ["\ufeff", "\u200b", "\u200d", "\u202e", "\u2060"])
def test_csv_invisible_format_controls_refuse_without_normalizing_observed_text(
    control: str,
) -> None:
    for value in (control + "=1+1", "ordinary" + control + "text"):
        with pytest.raises(RenderDenied, match="unsafe_csv_cell"):
            safe_csv(value)
