"""No raw source/credential/lease data can enter the broker work envelope."""

from uuid import uuid4

import pytest
from emailmonitor.progress.broker import ExecutionEvent
from pydantic import ValidationError


def body() -> dict[str, object]:
    return {
        "organization_id": str(uuid4()),
        "job_id": str(uuid4()),
        "item_id": str(uuid4()),
        "event_id": str(uuid4()),
        "generation": 1,
    }


@pytest.mark.parametrize("field", ["html", "url", "session_token", "lease_token", "email"])
def test_untrusted_content_and_credentials_refuse(field: str) -> None:
    document = body()
    document[field] = "untrusted"
    with pytest.raises(ValidationError):
        ExecutionEvent.model_validate(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", "not-a-uuid"),
        ("generation", 0),
        ("generation", True),
        pytest.param("job_id", str(uuid4()).upper(), id="job_id-uppercase-uuid"),
    ],
)
def test_invalid_work_identity_refuses(field: str, value: object) -> None:
    document = body()
    document[field] = value
    with pytest.raises(ValidationError):
        ExecutionEvent.model_validate(document)


def test_ids_only_canonical_envelope_roundtrip() -> None:
    event = ExecutionEvent.model_validate(body())
    assert ExecutionEvent.model_validate_json(event.model_dump_json()) == event
