"""Closed test-journey selection and CI receipt guards; actual UI proof is separate."""

import ast
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]


def provider_branch() -> ast.If:
    module = ast.parse((ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text())
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_provider'"
    )


@pytest.mark.parametrize("value", [None, "true", "false", 0, 1, [], {}])
def test_direct_url_selector_rejects_non_boolean_bootstrap(value: object) -> None:
    branch = provider_branch()
    code = compile(ast.Module(body=branch.body[:2], type_ignores=[]), "<closed-selector>", "exec")
    with pytest.raises(ValueError, match="Fixed controlled operator input required"):
        exec(code, {"setup": {"direct_article_url": value}})


@pytest.mark.parametrize(
    "setup,expected",
    [({}, False), ({"direct_article_url": False}, False), ({"direct_article_url": True}, True)],
)
def test_direct_url_selector_preserves_keyword_default(
    setup: dict[str, object], expected: bool
) -> None:
    namespace: dict[str, Any] = {"setup": setup}
    exec(
        compile(
            ast.Module(body=provider_branch().body[:2], type_ignores=[]),
            "<closed-selector>",
            "exec",
        ),
        namespace,
    )
    assert namespace["direct_url"] is expected


@pytest.mark.parametrize("direct", [False, True])
def test_keyboard_input_branch_uses_only_fixed_authored_inputs(direct: bool) -> None:
    branch = next(
        node
        for node in ast.walk(provider_branch())
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "direct_url"
        and "Search-results or article URL" in ast.unparse(node)
    )
    calls: list[tuple[object, ...]] = []

    class Page:
        def get_by_role(self, role: str, *, name: str, exact: bool) -> str:
            assert role == "button" and name == "URL" and exact
            return name

        def get_by_label(self, label: str, *, exact: bool) -> str:
            assert exact
            return label

    async def activate(page: Page, target: str) -> None:
        calls.append(("activate", target))

    async def type_text(page: Page, target: str, value: str) -> None:
        calls.append(("type", target, value))

    namespace: dict[str, Any] = {
        "direct_url": direct,
        "page": Page(),
        "activate": activate,
        "type_text": type_text,
    }
    wrapper = ast.parse("async def exercise():\n    pass\n")
    function = wrapper.body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    function.body = [branch]
    exec(compile(ast.fix_missing_locations(wrapper), "<fixed-input>", "exec"), namespace)
    asyncio.run(namespace["exercise"]())
    assert calls == (
        [
            ("activate", "URL"),
            (
                "type",
                "Search-results or article URL",
                "https://synthetic.publisher.example/provider-doi.xml",
            ),
        ]
        if direct
        else [("type", "Keyword", "Controlled provider journey")]
    )


@pytest.mark.parametrize(
    "kind", ["both", "keyword_only", "direct_only", "one_pass", "skipped", "pytest_failure"]
)
def test_operator_gate_requires_both_actual_receipts_and_two_passes(
    tmp_path: Path, kind: str
) -> None:
    keyword = "NORMAL_OPERATOR_RABBITMQ_PROVIDER_ISOLATED_REVIEW_EXPORT"
    direct = "NORMAL_OPERATOR_DIRECT_XML_URL_ISOLATED_REVIEW_EXPORT"
    lines = [keyword, direct, "2 passed in 1.00s"]
    if kind == "keyword_only":
        lines.remove(direct)
    elif kind == "direct_only":
        lines.remove(keyword)
    elif kind == "one_pass":
        lines[-1] = "1 passed in 1.00s"
    elif kind == "skipped":
        lines[-1] = "2 passed, 1 skipped in 1.00s"
    executable = tmp_path / "uv"
    # This owned stub exercises only the shell guard, never service acceptance.
    executable.write_text(
        "#!/bin/sh\nprintf '%s\\n' "
        + " ".join("'" + line + "'" for line in lines)
        + "\nexit "
        + ("1" if kind == "pytest_failure" else "0")
        + "\n"
    )
    executable.chmod(0o700)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/packaging/check_xml_transport.sh"), "operator"],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "RUNNER_TEMP": str(tmp_path),
        },
        capture_output=True,
        timeout=5,
    )
    assert (result.returncode == 0) is (kind == "both")
