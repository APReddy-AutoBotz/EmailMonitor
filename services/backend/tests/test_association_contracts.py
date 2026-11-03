"""Actual model/API schema parity and stronger relational semantic checks."""

import json
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from api_client import APIClient
from emailmonitor.associations.api import ReviewInput, association_router
from emailmonitor.associations.models import Bundle
from emailmonitor.associations.service import translate
from emailmonitor.config import Settings
from emailmonitor.organizations.database import AuthorizationDenied, Database, RevisionConflict
from fastapi import FastAPI, Request
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[3]


def sample(name: str) -> dict[str, object]:
    return cast(
        dict[str, object], json.loads((ROOT / f"contracts/examples/{name}.json").read_text())
    )


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((ROOT / f"contracts/{name}.schema.json").read_text()),
        format_checker=FormatChecker(),
    )


def test_committed_examples_validate_runtime_and_schema() -> None:
    bundle = sample("association-bundle")
    validator("association-bundle").validate(bundle)
    assert Bundle.model_validate_json(json.dumps(bundle)).model_dump(mode="json") == bundle
    request = sample("association-review-request")
    validator("association-review-request").validate(request)
    assert ReviewInput.model_validate(request).internal().action == "accept"


@pytest.mark.parametrize(
    "change",
    [
        {"raw_address": "new@example.org"},
        {"expected_revision": 0},
        {"expected_revision": True},
        {"evidence_ids": []},
        {"action": "send"},
        {"reason": "   "},
        {"batch_id": "a0000000000040008000000000000002"},
        {"association_id": "urn:uuid:a0000000-0000-4000-8000-000000000001"},
    ],
)
def test_review_input_schema_and_http_model_refuse(change: dict[str, object]) -> None:
    request = {**sample("association-review-request"), **change}
    assert not validator("association-review-request").is_valid(request)
    with pytest.raises(ValidationError):
        ReviewInput.model_validate(request)


@pytest.mark.parametrize("state", ["accepted", "needs_review"])
def test_accepted_requires_real_author_and_relational_evidence(state: str) -> None:
    payload = sample("association-bundle")
    associations = cast(list[dict[str, object]], payload["associations"])
    associations[0]["author_id"] = None
    associations[0]["state"] = state
    if state == "accepted":
        assert not validator("association-bundle").is_valid(payload)
        with pytest.raises(ValidationError):
            Bundle.model_validate_json(json.dumps(payload))
    else:
        # An unmatched/possible association is not an accepted contact claim.
        assert validator("association-bundle").is_valid(payload)
        Bundle.model_validate_json(json.dumps(payload))


def test_uuid_reference_relationships_are_runtime_semantics() -> None:
    payload = sample("association-bundle")
    associations = cast(list[dict[str, object]], payload["associations"])
    associations[0]["author_id"] = str(UUID(int=8))
    assert validator("association-bundle").is_valid(payload)
    with pytest.raises(ValidationError):
        Bundle.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "code,error_type", [("EM009", AuthorizationDenied), ("EM409", RevisionConflict)]
)
def test_exact_pg8000_sqlstate_translation(code: str, error_type: type[Exception]) -> None:
    error = DBAPIError(
        "SELECT fixture", {}, Exception({"C": code, "M": "synthetic metadata"}), False
    )
    with pytest.raises(error_type):
        translate(error)


def test_unrelated_or_missing_driver_errors_are_not_masked() -> None:
    for original in (Exception({"C": "42501"}), None):
        error = DBAPIError("SELECT fixture", {}, cast(BaseException, original), False)
        with pytest.raises(DBAPIError) as raised:
            translate(error)
        assert raised.value is error


def test_production_api_refuses_before_database_and_openapi_is_actual() -> None:
    app = FastAPI()

    def token(request: Request) -> str:
        return "synthetic"

    app.include_router(
        association_router(
            cast(Database, object()), token, token, Settings(environment="production")
        )
    )
    with APIClient(app, base_url="https://app.example.test") as client:
        assert (
            client.get(
                f"/organizations/{UUID(int=1)}/association-batches/{UUID(int=2)}"
            ).status_code
            == 404
        )
    schema = app.openapi()
    response = schema["paths"]["/organizations/{organization_id}/association-batches/{batch_id}"][
        "get"
    ]["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/Bundle")
    assert "raw_address" not in schema["components"]["schemas"]["ReviewInput"]["properties"]


def test_deletion_fence_uses_actual_retained_observation_and_organization_schema() -> None:
    migration = (ROOT / "services/backend/migrations/versions/0006_associations.sql").read_text()
    assert "a.deletion_generation<>o.deletion_generation" in migration
    assert "a.deletion_generation=b.deletion_generation" in migration
    assert "o.deletion_generation=b.deletion_generation" in migration
    # The existing jobs schema has a lifecycle generation, not a deletion epoch.
    assert "j.deletion_generation" not in migration
