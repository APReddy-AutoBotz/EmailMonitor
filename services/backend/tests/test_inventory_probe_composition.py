"""Pure trusted-source composition checks; actual image observation is a CI gate."""

import ast
from pathlib import Path
from types import FunctionType

import pytest
from inventory_probe import inventory_probe

from artifacts import PackagingRefused

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("kind", ["metadata", "xml"])
def test_composed_probe_compiles_without_collecting_at_import(kind: str, tmp_path: Path) -> None:
    from test_base_inventory import valid_base_inventory

    expected = valid_base_inventory(tmp_path / "base")
    source = inventory_probe(ROOT, kind)
    namespace: dict[str, object] = {"__name__": "composition_test"}
    exec(compile(source, "<trusted-composed-probe>", "exec"), namespace)
    collector = namespace["collect_base_inventory"]
    main = namespace["main"]
    assert callable(collector) and isinstance(main, FunctionType)
    assert main.__globals__["collect_base_inventory"] is collector
    assert collector(tmp_path / "base") == expected
    tree = ast.parse(source)
    main_node = next(
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "main"
    )
    calls = [n for n in ast.walk(main_node) if isinstance(n, ast.Call)]
    collect = [
        n for n in calls if isinstance(n.func, ast.Name) and n.func.id == "collect_base_inventory"
    ]
    assert len(collect) == 1 and not collect[0].args and not collect[0].keywords
    assert '"base_inventory"' in source


@pytest.mark.parametrize("kind", ["", "../xml_probe.py", "provider", "metadata;command"])
def test_only_fixed_probe_selection(kind: str) -> None:
    with pytest.raises(PackagingRefused, match="base_inventory_probe_kind_refused"):
        inventory_probe(ROOT, kind)


@pytest.mark.parametrize("component", ["base_inventory.py", "xml_probe.py"])
def test_composition_bounds_each_source(tmp_path: Path, component: str) -> None:
    folder = tmp_path / "scripts/packaging"
    folder.mkdir(parents=True)
    for name in ("base_inventory.py", "xml_probe.py"):
        (folder / name).write_bytes(b"x" * (32769 if name == component else 1))
    with pytest.raises(PackagingRefused, match="base_inventory_probe_size_refused"):
        inventory_probe(tmp_path, "xml")


def test_composition_refuses_non_utf8(tmp_path: Path) -> None:
    folder = tmp_path / "scripts/packaging"
    folder.mkdir(parents=True)
    (folder / "base_inventory.py").write_bytes(b"\xff")
    (folder / "xml_probe.py").write_text("pass")
    with pytest.raises(PackagingRefused, match="base_inventory_probe_encoding_refused"):
        inventory_probe(tmp_path, "xml")


def test_collector_is_not_an_image_build_input() -> None:
    from xml_artifacts import XML_FILES

    from artifacts import API_FILES

    assert not any("base_inventory" in name for name in (*API_FILES, *XML_FILES))
    for name in ("Metadata.Dockerfile", "XmlWorker.Dockerfile"):
        assert "base_inventory" not in (ROOT / "scripts/packaging" / name).read_text()
