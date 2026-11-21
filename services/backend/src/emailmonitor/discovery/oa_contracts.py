"""Generate the Open Access response contracts and examples from the models (OA-022).

    python -m emailmonitor.discovery.oa_contracts --write   # regenerate
    python -m emailmonitor.discovery.oa_contracts --check   # fail on drift

Schemas come from the Pydantic response models so code and contract cannot
silently diverge; examples are real outputs over the committed synthetic
fixtures with a pinned reference year.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from emailmonitor.discovery.document_intake import DocumentExtractionResult, extract_document
from emailmonitor.discovery.openaccess_orchestrator import DiscoveryResult, OpenAccessOrchestrator
from emailmonitor.results.researchers import ResearcherProfile, build_researcher_profiles

ROOT = Path(__file__).resolve().parents[5]
CONTRACTS = ROOT / "contracts"
REFERENCE_YEAR = 2026
SCHEMAS: dict[str, tuple[type[Any], str]] = {
    "oa-discovery-result.schema.json": (
        DiscoveryResult,
        "Open Access discovery result (preview). Shape only: evidence, roles and "
        "eligibility semantics are enforced by the extraction code and its tests.",
    ),
    "oa-document-extraction.schema.json": (
        DocumentExtractionResult,
        "Single supplied document (PDF, JATS XML or landing page) extraction result.",
    ),
    "oa-researcher-profile.schema.json": (
        ResearcherProfile,
        "Researcher rollup: grouped by address; linked only by a valid in-article ORCID.",
    ),
}


def schemas() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, (model, description) in SCHEMAS.items():
        schema = model.model_json_schema(mode="serialization")
        result[name] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://emailmonitor.invalid/contracts/{name}",
            "description": description,
            **{k: v for k, v in schema.items() if k != "description"},
        }
    return result


def examples() -> dict[str, dict[str, Any]]:
    orchestrator = OpenAccessOrchestrator(reference_year=REFERENCE_YEAR)
    discovery = orchestrator.discover_and_extract("PMC7700001", target_roles="all")
    page = (ROOT / "fixtures" / "publisher-html" / "highwire-article.html").read_bytes()
    document = extract_document(
        page,
        page_url="https://journal.publisher.example/sops/2026/0142",
        reference_year=REFERENCE_YEAR,
    )
    profiles = build_researcher_profiles(
        discovery.contacts_extracted, reference_year=REFERENCE_YEAR
    )
    return {
        "oa-discovery-result.json": discovery.model_dump(mode="json"),
        "oa-document-extraction.json": document.model_dump(mode="json"),
        "oa-researcher-profile.json": profiles[0].model_dump(mode="json"),
    }


def _render(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def expected_files() -> dict[Path, str]:
    files = {CONTRACTS / name: _render(schema) for name, schema in schemas().items()}
    files.update(
        {CONTRACTS / "examples" / name: _render(value) for name, value in examples().items()}
    )
    return files


def drift() -> list[str]:
    stale: list[str] = []
    for path, content in expected_files().items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            stale.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return stale


def main(argv: list[str]) -> int:
    if argv[1:] == ["--write"]:
        for path, content in expected_files().items():
            path.write_text(content, encoding="utf-8", newline="\n")
        return 0
    if argv[1:] == ["--check"]:
        stale = drift()
        for name in stale:
            print(f"stale contract: {name}")
        return 1 if stale else 0
    print("usage: python -m emailmonitor.discovery.oa_contracts --write|--check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
