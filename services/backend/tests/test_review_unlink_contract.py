"""Unlink remains an evidence-preserving review action, not an authority grant."""

import json
from pathlib import Path

import pytest
from emailmonitor.associations.api import ReviewInput
from emailmonitor.associations.models import Bundle
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


def test_review_request_and_bundle_contracts_allow_audited_unlink() -> None:
    request = json.loads((ROOT / "contracts/examples/association-review-request.json").read_text())
    request["action"] = "unlink"
    request["author_id"] = None
    schema = json.loads((ROOT / "contracts/association-review-request.schema.json").read_text())
    Draft202012Validator(schema).validate(request)
    assert ReviewInput.model_validate(request).internal().action == "unlink"
    document = json.loads((ROOT / "contracts/examples/association-bundle.json").read_text())
    document["associations"][0].update(
        state="needs_review",
        author_id=None,
        reason="reviewed_unlinked",
        evidence_strength="ambiguous",
    )
    schema = json.loads((ROOT / "contracts/association-bundle.schema.json").read_text())
    Draft202012Validator(schema).validate(document)
    assert Bundle.model_validate_json(json.dumps(document)).associations[0].state == "needs_review"
    request["action"] = "split_person"
    with pytest.raises(ValidationError):
        ReviewInput.model_validate(request)


def test_migration_declares_narrow_forward_only_transition_without_new_grants() -> None:
    path = ROOT / "services/backend/migrations/versions/0021_review_unlink.sql"
    sql = path.read_text()
    assert "GRANT " not in sql and "REVOKE " not in sql
    assert "emailmonitor.association_parent_fence" in sql
    assert "('owner','admin','data_steward','reviewer')" in sql
    assert "a.revision<>p_revision" in sql
    assert "a.record->'evidence_ids' IS DISTINCT FROM to_jsonb(p_evidence)" in sql
    assert "NEW.record->'evidence_ids' IS NOT DISTINCT FROM OLD.record->'evidence_ids'" in sql
    assert (
        "IF p_action<>'unlink' THEN\n  DELETE FROM emailmonitor.association_evidence_links" in sql
    )
    assert "'0021_review_unlink'" in sql
