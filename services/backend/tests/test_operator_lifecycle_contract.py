"""Closed fixture lifecycle bootstrap and fixed control grammar."""

import json
from unittest.mock import Mock

import pytest
from operator_ui_protocol import validate_journey
from run_operator_ui_acceptance import request_reply


def bootstrap() -> dict[str, object]:
    return {
        "kind": "bootstrap",
        "origin": "https://app.example.test",
        "journey": "controlled_lifecycle",
        "cookies": [],
        "assets": {},
        "initial_organization": "00000000-0000-4000-8000-000000000001",
        "other_organization": "00000000-0000-4000-8000-000000000002",
        "cancel_job": "00000000-0000-4000-8000-000000000003",
        "retry_job": "00000000-0000-4000-8000-000000000004",
    }


def test_lifecycle_bootstrap_requires_exact_owned_identifiers() -> None:
    valid = bootstrap()
    validate_journey(valid)
    for field in valid:
        with pytest.raises(ValueError):
            validate_journey({k: v for k, v in valid.items() if k != field})
    for patch in (
        {"url": "https://untrusted.example"},
        {"cancel_job": "arbitrary"},
        {"retry_job": valid["cancel_job"]},
        {"retry_job": 1},
    ):
        with pytest.raises(ValueError):
            validate_journey({**valid, **patch})


@pytest.mark.parametrize("action", ["hold_lifecycle_reply", "release_lifecycle_reply"])
def test_lifecycle_controls_are_fixed_without_arguments(action: str) -> None:
    control = Mock()
    frame = {"kind": "control", "identifier": 1, "action": action}
    reply = request_reply(Mock(), control, json.dumps(frame).encode(), Mock())
    assert reply["status"] == 200
    control.assert_called_once_with(action)
    with pytest.raises(RuntimeError, match="Owned UI request failed"):
        request_reply(Mock(), control, json.dumps({**frame, "job": "arbitrary"}).encode(), Mock())
    assert control.call_count == 1


def test_added_case_does_not_relax_original_workflow_pin() -> None:
    import hashlib
    from pathlib import Path

    from test_private_affiliation_diagnostic_workflow import (
        PRESERVED_BOUNDARIES,
        lifecycle_operator_baseline,
    )

    original = (
        Path(__file__).resolve().parents[3] / ".github/workflows/operator-ui.yml"
    ).read_bytes()
    expected = PRESERVED_BOUNDARIES[".github/workflows/operator-ui.yml"]
    assert hashlib.sha256(lifecycle_operator_baseline(original)).hexdigest() == expected
    for bad in (
        original.replace(b"timeout-minutes: 20", b"timeout-minutes: 21"),
        original.replace(b"permissions:\n  contents: read", b"permissions: write-all"),
        original.replace(b" -v -s\n", b" -v -s || true\n"),
        original.replace(b"test_operator_lifecycle_acceptance.py", b"optional.py"),
        original.replace(b"test_operator_ui_acceptance.py ", b""),
    ):
        try:
            normalized = lifecycle_operator_baseline(bad)
        except AssertionError:
            continue
        assert hashlib.sha256(normalized).hexdigest() != expected
