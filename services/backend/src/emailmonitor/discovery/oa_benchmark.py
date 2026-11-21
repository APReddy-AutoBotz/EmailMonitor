"""Offline association benchmark over an annotated document corpus (OA-025).

    python -m emailmonitor.discovery.oa_benchmark [MANIFEST]   # prints a JSON report

Each manifest document is a JATS/HTML file or a list of PDF text lines with
hand-written expectations: every address that should be reported, its owner
(or ``null`` when it belongs to no listed person) and the expected
corresponding-author role. Documents run through the same intake path as the
product (``extract_document`` with ``target_roles="all"``).

Error classes, most severe first:

* ``wrong_person`` — an address linked to someone other than its owner
  (including linking an ownerless mailbox to a person). Must stay zero.
* ``extra_address`` — an address reported that the annotation does not list
  (for a literal corpus this means sliced, joined or invented text).
* ``role_mismatch`` — correct owner, wrong corresponding-author role.
* ``missed_link`` / ``missed_address`` — conservative misses.

With the committed synthetic corpus this is a regression benchmark for the
association logic, not a measurement of real-world precision (EM-016).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from emailmonitor.discovery.document_intake import extract_document

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[5] / "fixtures" / "oa-benchmark" / "manifest.json"
)
PdfBuilder = Callable[[Sequence[str]], bytes]


def _document_bytes(entry: dict[str, Any], root: Path, pdf_builder: PdfBuilder | None) -> bytes:
    if "file" in entry:
        return (root / str(entry["file"])).read_bytes()
    if pdf_builder is None:
        raise RuntimeError("pdf_builder_required")
    return pdf_builder([str(line) for line in entry["pdf_lines"]])


def run_benchmark(
    manifest_path: Path = DEFAULT_MANIFEST,
    pdf_builder: PdfBuilder | None = None,
    reference_year: int = 2026,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    totals: Counter[str] = Counter()
    by_basis: dict[str, Counter[str]] = {}
    documents: list[dict[str, Any]] = []
    for entry in manifest["documents"]:
        result = extract_document(
            _document_bytes(entry, root, pdf_builder),
            known_authors=list(entry.get("known_authors", [])),
            target_roles="all",
            reference_year=reference_year,
        )
        predicted = {c.email.casefold(): c for c in result.contacts}
        expected = {str(e["address"]).casefold(): e for e in entry["expected"]}
        issues: list[str] = []
        for key, want in expected.items():
            got = predicted.get(key)
            if got is None:
                totals["missed_address"] += 1
                issues.append(f"missed_address:{want['address']}")
                continue
            basis = got.association_basis
            counter = by_basis.setdefault(basis, Counter())
            owner = want["author"]
            if got.author_name is not None and got.author_name != owner:
                totals["wrong_person"] += 1
                counter["wrong_person"] += 1
                issues.append(f"wrong_person:{want['address']}->{got.author_name}")
            elif owner is None:
                totals["correct_unlinked"] += 1
                counter["correct_unlinked"] += 1
            elif got.author_name is None:
                totals["missed_link"] += 1
                counter["missed_link"] += 1
                issues.append(f"missed_link:{want['address']}")
            else:
                totals["correct_link"] += 1
                counter["correct_link"] += 1
                role = want.get("corresponding")
                if role is not None and bool(got.is_corresponding_author) != role:
                    totals["role_mismatch"] += 1
                    counter["role_mismatch"] += 1
                    issues.append(f"role_mismatch:{want['address']}")
        for key, got in predicted.items():
            if key not in expected:
                totals["extra_address"] += 1
                issues.append(f"extra_address:{got.email}")
        documents.append({"id": entry["id"], "pattern": entry["pattern"], "issues": issues})

    linked = totals["correct_link"] + totals["wrong_person"]
    expected_links = (
        totals["correct_link"]
        + totals["missed_link"]
        + sum(1 for d in documents for i in d["issues"] if i.startswith("wrong_person"))
    )
    return {
        "corpus": manifest.get("description", ""),
        "documents": len(documents),
        "totals": dict(sorted(totals.items())),
        "link_precision": round(totals["correct_link"] / linked, 4) if linked else None,
        "link_recall": (
            round(totals["correct_link"] / expected_links, 4) if expected_links else None
        ),
        "by_basis": {k: dict(sorted(v.items())) for k, v in sorted(by_basis.items())},
        "issues": {d["id"]: d["issues"] for d in documents if d["issues"]},
    }


def main(argv: Sequence[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_MANIFEST
    tests_dir = Path(__file__).resolve().parents[3] / "tests"
    sys.path.insert(0, str(tests_dir))
    try:
        from pdf_fixture_builder import document
    finally:
        sys.path.remove(str(tests_dir))

    def build(lines: Sequence[str]) -> bytes:
        return bytes(document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]]))

    report = run_benchmark(path, build)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["totals"].get("wrong_person") or report["totals"].get("extra_address") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
