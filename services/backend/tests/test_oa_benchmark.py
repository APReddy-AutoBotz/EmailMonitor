"""The synthetic association benchmark stays clean (OA-025)."""

from collections.abc import Sequence

from emailmonitor.discovery.oa_benchmark import run_benchmark
from pdf_fixture_builder import document


def _pdf(lines: Sequence[str]) -> bytes:
    return document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])


def test_synthetic_benchmark_has_no_wrong_person_or_invented_address() -> None:
    report = run_benchmark(pdf_builder=_pdf)
    totals = report["totals"]
    assert report["documents"] >= 13
    assert totals.get("wrong_person", 0) == 0, report["issues"]
    assert totals.get("extra_address", 0) == 0, report["issues"]
    assert totals.get("role_mismatch", 0) == 0, report["issues"]
    assert totals.get("missed_address", 0) == 0, report["issues"]
    assert report["link_precision"] == 1.0
    assert report["link_recall"] == 1.0
    assert totals["correct_unlinked"] >= 4  # ownerless mailboxes stay unlinked
