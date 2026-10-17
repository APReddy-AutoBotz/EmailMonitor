"""Both existing two-build gates validate complete observed inventories and equality."""

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_base_inventory import valid_base_inventory


@pytest.mark.parametrize("kind", ["metadata", "xml"])
@pytest.mark.parametrize(
    "mutation", ["none", "missing", "extra", "digest", "duplicate", "different"]
)
def test_both_build_gates_validate_inventory_and_equality(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    mutation: str,
) -> None:
    import run_xml_acceptance
    from base_inventory import validate_base_inventory

    import run_acceptance

    module: Any = run_acceptance if kind == "metadata" else run_xml_acceptance
    inventory = valid_base_inventory(tmp_path / "base")
    files = {"manifest.json": b"{}"}
    closed: list[bool] = []

    def command(arguments: list[str], **kwargs: object) -> Any:
        value = ""
        if arguments[1:] == ["--version"]:
            value = {"uv": "uv 0.12.23", "pnpm": "11.25.0", "node": "v24.19.0"}[arguments[0]]
        elif arguments[:2] == ["git", "rev-parse"]:
            value = "a" * 40
        elif arguments[:2] == ["uv", "export"]:
            value = "pydantic==2.14.0\n"
        return (
            subprocess.CompletedProcess(arguments, 0, value, "")
            if kind == "metadata"
            else value.encode()
        )

    class Owned:
        def __init__(self, owner: str) -> None:
            self.owner = owner

        def build(self, context: Path, ordinal: int) -> tuple[str, str]:
            return "owned:" + str(ordinal), "sha256:" + str(ordinal) * 64

        def result(self, ordinal: int) -> dict[str, Any]:
            report = copy.deepcopy(inventory)
            if mutation == "extra":
                report["unexpected"] = True
            elif mutation == "digest":
                report["inventory_sha256"] = "0" * 64
            elif mutation == "duplicate":
                packages = report["packages"]
                assert isinstance(packages, list)
                packages.append(packages[0])
            elif mutation == "different" and ordinal == 2:
                # A second valid inventory must still fail build equality.
                import hashlib

                upstream = report["upstream_python"]
                assert isinstance(upstream, dict)
                upstream["executable_sha256"] = "b" * 64
                del report["inventory_sha256"]
                report["inventory_sha256"] = hashlib.sha256(
                    json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                validate_base_inventory(report)
            result: dict[str, Any] = {
                "scope": "metadata-only-offline-prerequisite"
                if kind == "metadata"
                else module.SCOPE,
                "working_extraction_service": False,
                "production_ready": False,
                "interfaces": ["lo"],
                "runtime_distributions": {"pydantic": "2.14.0"},
                "kernel_restrictions": True,
                "network_errno": [101, 101],
                "image_content_sha256": "c" * 64,
            }
            if mutation != "missing":
                result["base_inventory"] = report
            if kind == "metadata":
                result.update(
                    metadata_asgi=True,
                    forged_tenant_404=True,
                    fixture_code_absent=True,
                    production_refusals=8,
                )
            else:
                result.update(
                    synthetic_test_only=True,
                    fixture_assets_absent=True,
                    full_service=False,
                    exact_source_closure=True,
                    source_file_count=len(module.XML_FILES),
                    manifest_sha256=module.digest(files["manifest.json"]),
                )
            return result

        def smoke(self, image: str, probe: str, ordinal: int) -> dict[str, Any]:
            assert "def collect_base_inventory" in probe
            return self.result(ordinal)

        def probe(self, image: str, probe: str, ordinal: int) -> dict[str, Any]:
            return self.smoke(image, probe, ordinal)

        def worker(self, image: str, ordinal: int, data: bytes) -> list[str]:
            return ["valid"]  # Existing actual seven-case execution has its own tests/gate.

        def close(self) -> None:
            closed.append(True)

    def materialize(inputs: dict[str, bytes], path: Path) -> None:
        path.mkdir()

    monkeypatch.setattr(module, "command", command)
    monkeypatch.setattr(module, "require_ci", lambda environ: None)
    monkeypatch.setattr(module, "collect", lambda *args: files)
    monkeypatch.setattr(module, "verify_archive", lambda *args: files)
    monkeypatch.setattr(module, "materialize", materialize)
    monkeypatch.setattr(module, "OwnedBuilds" if kind == "metadata" else "OwnedXmlBuilds", Owned)
    if mutation == "none":
        module.main()
        output = capsys.readouterr().out
        assert '"base_inventory_equal": true' in output
        assert str(inventory["inventory_sha256"]) in output
    else:
        with pytest.raises(RuntimeError):
            module.main()
        assert '"base_inventory_equal": true' not in capsys.readouterr().out
    assert closed == [True]
