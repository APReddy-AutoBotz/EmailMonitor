"""Offline batch intake CLI over a folder of supplied documents (OA-024)."""

import csv
import io
import shutil
from pathlib import Path

import pytest
from emailmonitor.discovery.batch_intake import MAX_FILES, main, run
from emailmonitor.fetching.safety import FetchDenied
from pdf_fixture_builder import document

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(FIXTURES / "jats" / "usher-base-editing.xml", folder / "usher.xml")
    shutil.copy(FIXTURES / "publisher-html" / "highwire-article.html", folder / "page.html")
    (folder / "paper.pdf").write_bytes(
        document(
            [[(72.0, 720.0, 9.0, "*Correspondence: Pieter de Vries, p.devries@delft.example")]]
        )
    )
    (folder / "notes.txt").write_text("ignored")
    (folder / "broken.xml").write_bytes(b"<article><front>")
    return folder


def test_run_processes_supported_files_and_isolates_failures(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    authors = tmp_path / "authors.csv"
    authors.write_text("file,authors\npaper.pdf,Amara Diallo; Pieter de Vries\n", encoding="utf-8")
    contacts, outcomes = run(folder, authors_csv=authors, reference_year=2026)
    by_file = {o.name: o for o in outcomes}
    assert set(by_file) == {"usher.xml", "page.html", "paper.pdf", "broken.xml"}
    assert by_file["broken.xml"].status == "failed"
    assert by_file["paper.pdf"].contacts == 1
    devries = next(c for c in contacts if c.email == "p.devries@delft.example")
    assert devries.author_name == "Pieter de Vries" and devries.is_corresponding_author


def test_cli_writes_csv_and_refuses_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _folder(tmp_path)
    out = tmp_path / "out.csv"
    assert main([str(folder), "--out", str(out), "--preset", "evidence"]) == 0
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert {r["email"] for r in rows} >= {
        "t.nowak@genetics.krakow.example",
        "y.haddad@arid.amman.example",
    }
    assert all(r["content_sha256"] and r["evidence_excerpt"] for r in rows)
    assert "broken.xml: failed" in capsys.readouterr().err
    assert main([str(folder), "--out", str(out)]) == 2  # never overwrites


def test_cli_strength_and_suppression(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    out = tmp_path / "strict.csv"
    code = main(
        [
            str(folder),
            "--out",
            str(out),
            "--preset",
            "smartlead",
            "--minimum-strength",
            "structural",
            "--suppress-domains",
            "uppsala.example",
        ]
    )
    assert code == 0
    emails = {r["Email"] for r in csv.DictReader(io.StringIO(out.read_text(encoding="utf-8")))}
    assert "saga.lindgren@agri.uppsala.example" not in emails  # suppressed domain
    assert "lucia.ferreira@neuro.lisbon.example" not in emails  # labelled, below structural
    assert "r.mehta@bio.pune.example" in emails  # structural contrib email


def test_input_bounds(tmp_path: Path) -> None:
    with pytest.raises(FetchDenied, match="input_directory_missing"):
        run(tmp_path / "missing")
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(MAX_FILES + 1):
        (folder / f"f{i}.html").write_text("<html></html>")
    with pytest.raises(FetchDenied, match="too_many_input_files"):
        run(folder)
