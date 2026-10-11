"""Static restrictive configuration checks; these do not certify OS isolation."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_parser_only_workflow_has_no_browser_or_expanded_permissions() -> None:
    workflow = (ROOT / ".github/workflows/parser-isolation.yml").read_text()
    assert "run: python3 scripts/isolation/run_parser_acceptance.py" in workflow
    assert "contents: read" in workflow and "persist-credentials: false" in workflow
    assert "browser" not in workflow.lower() and "seccomp" not in workflow.lower()
    assert "pull_request_target" not in workflow


def test_container_runner_only_restricts_default_capabilities_and_network() -> None:
    runner = (ROOT / "scripts/isolation/run_parser_acceptance.py").read_text()
    for required in (
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--user=65532:65532",
        "--memory=128m",
        "--memory-swap=128m",
        "--cpus=0.5",
        "--pids-limit=32",
        "--ulimit=core=0:0",
    ):
        assert required in runner
    for forbidden in (
        "--privileged",
        "--cap-add",
        "--network=host",
        "seccomp=unconfined",
        "--mount",
        "docker.sock",
        "--volume",
        "sysctl",
        "iptables",
        "--no-sandbox",
    ):
        assert forbidden not in runner
    assert 'after["OOMKilled"]' in runner
    assert 'os.environ.get("GITHUB_ACTIONS") != "true"' in runner


def test_pinned_parser_image_and_minimal_context_are_consistent() -> None:
    inventory = json.loads((ROOT / "reports/runtime-inventory.json").read_text())
    dockerfile = (ROOT / "scripts/isolation/Dockerfile.parser").read_text()
    assert "FROM " + inventory["python_parser"]["ci_image"] + "\n" in dockerfile
    assert "@sha256:" in inventory["python_parser"]["ci_image"]
    assert "USER 65532:65532" in dockerfile
    context = (ROOT / ".dockerignore").read_text()
    assert context.startswith("**\n") and "!services/backend/uv.lock" in context
    assert "!services/backend/.venv" not in context and "**/__pycache__" in context


def test_parser_network_probe_uses_only_documentation_addresses_and_guard() -> None:
    diagnostic = (ROOT / "scripts/isolation/parser_acceptance.py").read_text()
    assert 'interfaces != ["lo"]' in diagnostic
    assert '"192.0.2.1"' in diagnostic and '"2001:db8::1"' in diagnostic
    assert "169.254.169.254" not in diagnostic and "8.8.8.8" not in diagnostic
    assert 'os.environ.get("EM_ISOLATION_DIAGNOSTIC")' in diagnostic
