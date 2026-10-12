"""Exact reviewed PDF dependency/notice and isolation assembly, offline only."""

import hashlib
import json
import tomllib
from importlib.metadata import distribution
from pathlib import Path

from emailmonitor.extraction.pdf import PdfLimits, configuration

ROOT = Path(__file__).resolve().parents[3]


def test_exact_parser_artifact_license_and_no_optional_stack() -> None:
    locked = tomllib.loads((ROOT / "services/backend/uv.lock").read_text())["package"]
    parser = next(p for p in locked if p["name"] == "pypdf")
    assert parser["version"] == distribution("pypdf").version == "6.20.1"
    assert parser["source"] == {"registry": "https://pypi.org/simple"}
    assert (
        parser["wheels"][0]["hash"]
        == "sha256:aa5a55ddcffdc5e5ab291d5decb23f6383f4e56f8e3263dc39af41fff03885ad"
    )
    assert (
        parser["sdist"]["hash"]
        == "sha256:28f5a9d2fdc2749264612d94e6a58de54c11d730d9f0cabf8ad34117c4942b45"
    )
    assert not parser.get("dependencies")
    assert not {
        "pypdfium2",
        "pdfplumber",
        "pymupdf",
        "mupdf",
        "reportlab",
        "pillow",
        "brotli",
        "fonttools",
    } & {p["name"] for p in locked}
    installed = distribution("pypdf")
    assert installed.metadata["License-Expression"] == "BSD-3-Clause"
    notice = next(f for f in installed.files or [] if str(f).endswith("licenses/LICENSE"))
    assert (ROOT / "reports/licenses/pypdf-6.20.1-LICENSE.txt").read_bytes() == Path(
        str(installed.locate_file(notice))
    ).read_bytes()


def test_pdf_configuration_never_discovers_optional_external_decoder() -> None:
    limits = configuration(PdfLimits())
    assert limits.jbig2dec_binary is None
    assert limits.stream_decoding_work_maximum_length == 262144
    assert limits.page_tree_maximum_entries == 64
    assert limits.page_tree_maximum_depth == 16
    assert limits.maximum_declared_stream_length == 65536


def test_existing_parser_security_settings_and_only_reviewed_pdf_inputs() -> None:
    runner = (ROOT / "scripts/isolation/run_parser_acceptance.py").read_text()
    for setting in (
        "--network=none",
        "--cap-drop=ALL",
        "--read-only",
        "--memory=128m",
        "--security-opt=no-new-privileges",
        "--user=65532:65532",
    ):
        assert setting in runner
    dockerfile = (ROOT / "scripts/isolation/Dockerfile.parser").read_text()
    inventory = json.loads((ROOT / "reports/runtime-inventory.json").read_text())
    assert "FROM " + inventory["python_parser"]["ci_image"] + "\n" in dockerfile
    profile = ROOT / "scripts/isolation/seccomp-browser.json"
    assert (
        hashlib.sha256(profile.read_bytes()).hexdigest()
        == inventory["browser_seccomp"]["derived_sha256"]
    )
    assert "./fixtures/pdf/" in dockerfile
    assert "fixtures/expected" not in dockerfile and "manifest.json" not in dockerfile


def test_effective_glyph_data_terms_and_source_notices_are_preserved() -> None:
    inventory = json.loads((ROOT / "reports/dependency-inventory.json").read_text())
    entry = next(p for p in inventory["python"] if p["name"] == "pypdf")
    assert entry["declared_license"] == "BSD-3-Clause"
    assert entry["license"] == "BSD-3-Clause AND Unicode-3.0"
    notices = (ROOT / "reports/licenses/pypdf-6.20.1-SOURCE-NOTICES.txt").read_text()
    assert "UNICODE LICENSE V3" in notices and "Copyright 2002-2019 Adobe" in notices
    assert "LettError" in notices and "Copyright (c) 2023, exiledkingcc" in notices
    retained = 0
    distinct = set()
    installed = distribution("pypdf")
    for file in installed.files or []:
        if not str(file).startswith("pypdf/") or not str(file).endswith(".py"):
            continue
        leading = []
        for line in Path(str(installed.locate_file(file))).read_text().splitlines(keepends=True):
            if line.startswith("#") or not line.strip():
                leading.append(line)
            else:
                break
        text = "".join(leading).strip()
        if "Redistribution" in text and ("Copyright" in text or "copyright" in text):
            assert text in notices
            retained += 1
            distinct.add(text)
    assert retained == 20 and len(distinct) == 9
