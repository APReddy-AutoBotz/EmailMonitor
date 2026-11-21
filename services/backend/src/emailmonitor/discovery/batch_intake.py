"""Offline batch intake: a folder of supplied documents -> one export CSV (OA-024).

    python -m emailmonitor.discovery.batch_intake INPUT_DIR --out results.csv \\
        [--preset evidence|instantly|smartlead|lemlist|hubspot] \\
        [--authors authors.csv] [--roles all|both|corresponding|first] \\
        [--suppress-domains a.example,b.example] [--minimum-strength labelled|structural]

Reads ``*.pdf``, ``*.xml``, ``*.html``/``*.htm`` directly inside INPUT_DIR (no
recursion, no symlinks, at most 500 files of at most 20 MB each). Nothing is
fetched; links inside documents are never followed. ``--authors`` is an
optional CSV with columns ``file,authors`` where authors are separated by
semicolons, used only to link PDF addresses to names.

Output contains researcher contact data: write it outside the repository
(``/exports/`` and ``/data/`` are git-ignored) and handle it under the
organisation's retention policy. A per-file summary goes to stderr.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from emailmonitor.discovery.document_intake import MAX_DOCUMENT_BYTES, extract_document
from emailmonitor.discovery.openaccess_orchestrator import ExtractedAcademicContact
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.results.oa_exports import EXPORT_PRESETS, render_export

MAX_FILES = 500
SUFFIXES = frozenset({".pdf", ".xml", ".html", ".htm"})


@dataclass(frozen=True)
class FileOutcome:
    name: str
    status: str
    contacts: int
    detail: str = ""


def _authors_map(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    mapping: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("file") or "").strip()
            authors = [a.strip() for a in (row.get("authors") or "").split(";") if a.strip()]
            if name and authors:
                mapping[name] = authors[:100]
    return mapping


def collect(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise FetchDenied("input_directory_missing")
    files = sorted(
        p
        for p in directory.iterdir()
        if p.suffix.lower() in SUFFIXES and p.is_file() and not p.is_symlink()
    )
    if len(files) > MAX_FILES:
        raise FetchDenied("too_many_input_files")
    return files


def run(
    directory: Path,
    *,
    authors_csv: Path | None = None,
    roles: str = "all",
    suppressed_domains: Sequence[str] = (),
    reference_year: int | None = None,
) -> tuple[list[ExtractedAcademicContact], list[FileOutcome]]:
    authors = _authors_map(authors_csv)
    contacts: list[ExtractedAcademicContact] = []
    outcomes: list[FileOutcome] = []
    for path in collect(directory):
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            outcomes.append(FileOutcome(path.name, "skipped", 0, "larger than 20 MB"))
            continue
        try:
            result = extract_document(
                path.read_bytes(),
                known_authors=authors.get(path.name, ()),
                target_roles=roles,  # type: ignore[arg-type]
                suppressed_domains=suppressed_domains,
                reference_year=reference_year,
            )
        except (FetchDenied, ValueError) as exc:
            reason = str(exc) if isinstance(exc, FetchDenied) else "rejected_by_bounds"
            outcomes.append(FileOutcome(path.name, "failed", 0, reason[:200]))
            continue
        contacts.extend(result.contacts)
        notes = "; ".join(result.review_notes)
        outcomes.append(FileOutcome(path.name, result.status, len(result.contacts), notes))
    return contacts, outcomes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="batch_intake", description=__doc__.split("\n\n")[0])
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preset", choices=EXPORT_PRESETS, default="evidence")
    parser.add_argument("--authors", type=Path)
    parser.add_argument("--roles", choices=("all", "both", "corresponding", "first"), default="all")
    parser.add_argument("--suppress-domains", default="")
    parser.add_argument(
        "--minimum-strength", choices=("labelled", "structural"), default="labelled"
    )
    args = parser.parse_args(argv)
    if args.out.exists():
        print(f"refusing to overwrite existing file: {args.out}", file=sys.stderr)
        return 2
    try:
        contacts, outcomes = run(
            args.input_dir,
            authors_csv=args.authors,
            roles=args.roles,
            suppressed_domains=[d for d in args.suppress_domains.split(",") if d.strip()],
        )
    except FetchDenied as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    export = render_export(args.preset, contacts, args.minimum_strength)
    args.out.write_bytes(export.content)
    for outcome in outcomes:
        detail = f" ({outcome.detail})" if outcome.detail else ""
        print(
            f"{outcome.name}: {outcome.status}, {outcome.contacts} contact(s){detail}",
            file=sys.stderr,
        )
    print(
        f"wrote {export.rows_written} row(s) to {args.out}; "
        f"{export.rows_excluded_not_eligible} not eligible/below strength, "
        f"{export.rows_withheld_unsafe} withheld as formula-unsafe",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
