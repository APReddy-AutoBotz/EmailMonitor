"""Inactive contract tests; these do not establish durable PDF execution."""

import json
from uuid import uuid4

import pytest
from emailmonitor.extraction.pdf_fixture import DIGESTS
from emailmonitor.extraction.pdf_retained import (
    PdfBinding,
    RetainedPdf,
    require_pdf_binding,
    retain_pdf,
)
from test_pdf_extraction import parse


def binding() -> PdfBinding:
    return PdfBinding(
        organization=uuid4(),
        job=uuid4(),
        item=uuid4(),
        generation=1,
        deletion_generation=1,
        policy_version=1,
        discovery_revision=1,
    )


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_retained_pdf_preserves_exact_parser_facts(name: str) -> None:
    observed = parse(name)
    scope = binding()
    value = retain_pdf(observed, scope, permit_excerpts=True)
    assert value.content_digest == DIGESTS[name]
    assert value.status == observed.status
    assert value.reason == observed.reason
    assert value.complete_scan == observed.complete_scan
    assert value.authors == observed.authors
    assert value.candidates == observed.candidates
    assert value.metadata == observed.metadata
    assert require_pdf_binding(value, scope, permit_excerpts=True) == value
    assert (
        retain_pdf(observed, scope, permit_excerpts=True).model_dump_json()
        == value.model_dump_json()
    )


@pytest.mark.parametrize("field", list(PdfBinding.model_fields))
def test_retained_pdf_rejects_other_scope_or_revision(field: str) -> None:
    scope = binding()
    value = retain_pdf(parse("article-a.pdf"), scope, permit_excerpts=True)
    document = scope.model_dump()
    document[field] = uuid4() if field in {"organization", "job", "item"} else 2
    with pytest.raises(ValueError, match="Exact current PDF binding"):
        require_pdf_binding(value, PdfBinding.model_validate(document), permit_excerpts=True)


def test_retained_pdf_does_not_strip_literal_evidence_to_evade_retention() -> None:
    scope = binding()
    observed = parse("article-a.pdf")
    with pytest.raises(ValueError, match="Locator-only PDF retention"):
        retain_pdf(observed, scope, permit_excerpts=False)
    value = retain_pdf(observed, scope, permit_excerpts=True)
    with pytest.raises(ValueError, match="Current PDF excerpt retention"):
        require_pdf_binding(value, scope, permit_excerpts=False)


@pytest.mark.parametrize("name", ["encrypted.pdf", "corrupt.pdf", "scanned.pdf"])
def test_unsupported_retained_pdf_has_no_fabricated_facts(name: str) -> None:
    value = retain_pdf(parse(name), binding(), permit_excerpts=False)
    assert value.status == "unsupported"
    assert not value.excerpts_retained
    assert not value.authors and not value.candidates and not value.metadata
    assert not value.complete_scan


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_digest", "0" * 64),
        ("url", "https://synthetic.publisher.example/unknown.pdf"),
        ("input_mode", "live"),
        ("retention_profile", "unknown"),
        ("excerpts_retained", False),
        ("unexpected", True),
    ],
)
def test_retained_pdf_rejects_forged_envelope(field: str, value: object) -> None:
    original = retain_pdf(parse("article-a.pdf"), binding(), permit_excerpts=True)
    document = original.model_dump(mode="json")
    document[field] = value
    with pytest.raises(ValueError):
        RetainedPdf.model_validate_json(json.dumps(document))


def test_model_copy_does_not_bypass_binding_validation() -> None:
    scope = binding()
    value = retain_pdf(parse("article-a.pdf"), scope, permit_excerpts=True)
    forged = value.model_copy(update={"content_digest": "0" * 64})
    with pytest.raises(ValueError):
        require_pdf_binding(forged, scope, permit_excerpts=True)


def test_unprocessed_disabled_input_cannot_claim_retained_source_digest() -> None:
    with pytest.raises(ValueError, match="Exact authored PDF bytes"):
        retain_pdf(parse("article-a.pdf", allow_pdf=False), binding(), permit_excerpts=True)


def test_current_permission_decision_cannot_be_truthy_nonboolean() -> None:
    value = retain_pdf(parse("article-a.pdf"), binding(), permit_excerpts=True)
    with pytest.raises(ValueError):
        require_pdf_binding(value, value.binding, permit_excerpts=1)  # type: ignore[arg-type]
