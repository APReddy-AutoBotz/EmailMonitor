"""Pinned framework assembly warning race; all warning-state probes are child-local."""

import ast
import json
import os
import subprocess
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[3]


def probe(interleaved: bool, alias: str) -> dict[str, object]:
    import fastapi._compat.v2 as compat
    from emailmonitor.api import create_app
    from emailmonitor.config import Settings
    from emailmonitor.identity.foundation import Foundation
    from emailmonitor.identity.oidc import OIDCProvider
    from emailmonitor.organizations.database import AuthenticationDatabase, Database

    class NoDatabase:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError("No database access permitted in assembly probe")

    foundation = Foundation(
        cast(Database, NoDatabase()),
        cast(OIDCProvider, SimpleNamespace(test_only=True)),
        cast(AuthenticationDatabase, NoDatabase()),
    )
    settings = Settings(environment="test", identity_stub=True)
    original = vars(compat)["TypeAdapter"]
    local = threading.local()
    entered_a, entered_b, finished_a = (threading.Event() for _ in range(3))

    def adapter(annotation: Any, **kwargs: Any) -> Any:
        args = get_args(annotation)
        metadata = args[-1] if args else None
        if getattr(metadata, "alias", None) == alias and not getattr(local, "gated", False):
            local.gated = True
            if local.name == "a":
                entered_a.set()
                assert entered_b.wait(10)
            else:
                entered_b.set()
                assert finished_a.wait(10)
        return original(annotation, **kwargs)

    def build(name: str) -> FastAPI:
        local.name = name
        if interleaved and name == "b":
            assert entered_a.wait(10)
        result = create_app(settings, foundation)
        if name == "a":
            finished_a.set()
        return result

    baseline = warnings.filters[:]
    patch = pytest.MonkeyPatch()
    try:
        if interleaved:
            patch.setattr(compat, "TypeAdapter", adapter)
        # Capture, never ignore: dependency-owned nested warning contexts are
        # the behavior under test. A subprocess contains any global-filter leak.
        with warnings.catch_warnings(record=True) as observed:
            if interleaved:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first, second = pool.submit(build, "a"), pool.submit(build, "b")
                    apps = [first.result(timeout=15), second.result(timeout=15)]
            else:
                apps = [build("a"), build("b")]
            filters_restored_inside_capture = warnings.filters == baseline
        return {
            "warnings": [
                {"category": row.category.__name__, "message": str(row.message)} for row in observed
            ],
            "route_counts": [len(app.routes) for app in apps],
            "filters_restored_inside_capture": filters_restored_inside_capture,
            "outer_capture_restored": warnings.filters == baseline,
        }
    finally:
        patch.undo()


@pytest.mark.parametrize("interleaved", [False, True])
@pytest.mark.parametrize("alias", ["organization_id", "body", "batch_id"])
def test_pinned_app_assembly_warning_has_causal_interleaving(interleaved: bool, alias: str) -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__)), "interleaved" if interleaved else "serial", alias],
        env={**os.environ, "PYTHONPATH": str(ROOT / "services/backend/src")},
        capture_output=True,
        text=True,
        timeout=35,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["outer_capture_restored"] is True
    assert receipt["route_counts"] == [4, 4]
    if interleaved:
        assert receipt["filters_restored_inside_capture"] is False
        assert len(receipt["warnings"]) == 1
        assert receipt["warnings"][0]["category"] == "UnsupportedFieldAttributeWarning"
        assert f"'alias' attribute with value {alias!r}" in receipt["warnings"][0]["message"]
    else:
        assert receipt["filters_restored_inside_capture"] is True
        assert receipt["warnings"] == []
    assert result.stderr == ""


def test_last_owner_race_keeps_app_assembly_outside_request_threads() -> None:
    module = ast.parse((ROOT / "services/backend/tests/test_tenant_foundation.py").read_text())
    test = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_concurrent_last_owner_removal_is_serialized"
    )
    remove = next(
        node
        for node in ast.walk(test)
        if isinstance(node, ast.FunctionDef) and node.name == "remove"
    )
    source = ast.unparse(remove)
    assert "create_app(" not in source and "Database(" not in source and "Foundation(" not in source
    assert "scenario.login(client, role)" in source
    assert "barrier.wait(timeout=10)" in source and "client.patch(" in source
    whole = ast.unparse(test)
    assert "ThreadPoolExecutor(max_workers=2)" in whole
    assert "sorted(results) == [200, 409]" in whole
    assert whole.index("create_app(", whole.index("with ExitStack()")) < whole.index(
        "ThreadPoolExecutor(max_workers=2)"
    )
    assert "resources.callback(db.engine.dispose)" in whole


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1] == "interleaved", sys.argv[2])))
