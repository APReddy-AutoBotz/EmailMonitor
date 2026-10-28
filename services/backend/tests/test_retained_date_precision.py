"""Retained source text stays intact; precision never supplies a missing date."""

import pytest
from emailmonitor.associations.date_precision import retained_date_precision


@pytest.mark.parametrize(
    ("text", "precision"),
    [
        ("2026", "year"),
        ("2026-02", "month"),
        ("2024-02-29", "day"),
        ("2026-01-15", "day"),
        ("2026-02-29", "unrecognized"),
        ("0000", "unrecognized"),
        ("2026-13", "unrecognized"),
        ("2026-2-1", "unrecognized"),
        ("Spring 2026", "unrecognized"),
        ("2026-01-15T00:00:00Z", "unrecognized"),
        (" 2026-01-15 ", "unrecognized"),
    ],
)
def test_precision_requires_unmodified_valid_iso_text(text: str, precision: str) -> None:
    assert retained_date_precision(text) == precision
