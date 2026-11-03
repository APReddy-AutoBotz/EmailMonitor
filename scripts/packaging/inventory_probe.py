"""Trusted fixed source composition; collector code never enters an image layer."""

from pathlib import Path

from artifacts import PackagingRefused, read


def inventory_probe(root: Path, kind: str) -> str:
    probes = {"metadata": "probe.py", "xml": "xml_probe.py"}
    if kind not in probes:
        raise PackagingRefused("base_inventory_probe_kind_refused")
    prefix = read(root, "scripts/packaging/base_inventory.py")
    probe = read(root, "scripts/packaging/" + probes[kind])
    if len(prefix) > 32768 or len(probe) > 32768:
        raise PackagingRefused("base_inventory_probe_size_refused")
    try:
        return prefix.decode("utf-8") + "\n" + probe.decode("utf-8")
    except UnicodeError:
        raise PackagingRefused("base_inventory_probe_encoding_refused") from None
