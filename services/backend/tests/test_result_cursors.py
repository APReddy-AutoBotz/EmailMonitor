"""Cursors are canonical navigation only; current authority is never supplied by them."""

import base64
import json
from uuid import uuid4

import pytest
from emailmonitor.results.cursor import decode, encode
from emailmonitor.results.models import Filters
from pydantic import ValidationError


def test_round_trip_and_empty_cursor() -> None:
    org, first, second = uuid4(), uuid4(), uuid4()
    filters = Filters(job_id=uuid4())
    cursor = encode(org, "contacts", filters, first, second)
    assert decode(org, "contacts", filters, cursor) == (first, second)
    assert decode(org, "contacts", filters, None) is None


@pytest.mark.parametrize("change", ["tenant", "kind", "job", "states", "query", "target"])
def test_cursor_scope_changes_refuse(change: str) -> None:
    org = uuid4()
    filters = Filters(job_id=uuid4())
    cursor = encode(org, "contacts", filters, uuid4(), uuid4())
    with pytest.raises(ValueError):
        decode(
            uuid4() if change == "tenant" else org,
            "outcomes" if change == "kind" else "contacts",
            Filters(job_id=uuid4())
            if change == "job"
            else filters.model_copy(update={"states": ("needs_review",)})
            if change == "states"
            else filters.model_copy(update={"query": "different"})
            if change == "query"
            else filters.model_copy(update={"author_target": "first"})
            if change == "target"
            else filters,
            cursor,
        )


@pytest.mark.parametrize(
    "change", ["padding", "newline", "extra", "bool", "uuid", "object", "size"]
)
def test_noncanonical_or_malformed_cursor_refuses(change: str) -> None:
    org = uuid4()
    filters = Filters()
    cursor = encode(org, "contacts", filters, uuid4(), uuid4())
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    if change == "padding":
        cursor += "="
    elif change == "newline":
        cursor += "\n"
    elif change == "size":
        cursor = "A" * 2049
    else:
        if change == "extra":
            payload.append("extra")
        elif change == "bool":
            payload[0] = True
        elif change == "uuid":
            payload[4] = payload[4].replace("-", "")
        else:
            payload = {"authorization": "owner"}
        cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        decode(org, "contacts", filters, cursor)


@pytest.mark.parametrize(
    "payload",
    [
        {"states": ()},
        {"states": ("accepted", "accepted")},
        {"query": "bad\x00text"},
        {"query": "x" * 101},
        {"states": ("suppressed",)},
        {"query": "bad\ud800text"},
    ],
)
def test_filter_shape_is_bounded_and_suppressed_records_unavailable(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Filters.model_validate(payload)
