"""Network-free operator inputs and allowlisted immutable export formatting."""

import csv
import io
import json

import pytest
from emailmonitor.operator.api import ProfileUpdate
from emailmonitor.results.models import ExportInput
from emailmonitor.results.render import render
from pydantic import ValidationError
from test_result_serialization import snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {"display_name": " "},
        {"display_name": "unsafe\nname"},
        {"timezone": "not/a-zone"},
        {"expected_revision": True},
        {"expected_revision": 0},
        {"region": "new-region"},
        {"status": "suspended"},
    ],
)
def test_profile_edit_is_only_printable_name_known_timezone_and_revision(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate(
            {
                "display_name": "Synthetic organization",
                "timezone": "UTC",
                "expected_revision": 1,
                **changes,
            }
        )


def test_profile_allows_existing_iana_timezone_without_security_settings() -> None:
    value = ProfileUpdate(
        display_name="Authored organization", timezone="Asia/Kolkata", expected_revision=2
    )
    assert set(value.model_dump()) == {"display_name", "timezone", "expected_revision"}


@pytest.mark.parametrize(
    "fields", [[], ["affiliations"], ["article_title"], ["affiliations", "article_title"]]
)
def test_optional_export_columns_never_remove_observed_or_permission_facts(
    fields: list[str],
) -> None:
    request = ExportInput.model_validate(
        {"format": "csv", "purpose": "academic_contact_research", "optional_contact_fields": fields}
    )
    doc = snapshot(outcomes=False).model_dump(mode="json")
    doc["optional_contact_fields"] = list(request.optional_contact_fields)
    selected = type(snapshot()).model_validate_json(json.dumps(doc))
    rows = list(csv.reader(io.StringIO(render(selected).body.decode())))
    assert ("Affiliations" in rows[0]) == ("affiliations" in fields)
    assert ("Article title" in rows[0]) == ("article_title" in fields)
    for name in [
        "Observed address",
        "First author",
        "Corresponding author",
        "Association state",
        "Identity state",
        "Source URL",
        "Policy version",
        "Technical status",
        "Outreach eligibility",
    ]:
        assert name in rows[0]
    assert len(rows[0]) == len(rows[1])


@pytest.mark.parametrize(
    "fields",
    [["affiliations", "affiliations"], ["raw_address"], ["outreach_eligibility"], [1], None],
)
def test_export_optional_fields_cannot_remove_mandatory_columns_or_add_unknown_fields(
    fields: object,
) -> None:
    with pytest.raises(ValidationError):
        ExportInput.model_validate(
            {
                "format": "csv",
                "purpose": "academic_contact_research",
                "optional_contact_fields": fields,
            }
        )
