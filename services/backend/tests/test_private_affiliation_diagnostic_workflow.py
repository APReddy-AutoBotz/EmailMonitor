"""Read-only one-shot workflow contracts; no runner import, Docker, Git or network.

These expectations bind the narrowly reviewed docs/64 composition to the accepted
PR42/PR43 boundaries. They are not a substitute for the independent frozen-tree
review, GitHub event admission, or the separate actual initial-event outcome.
"""

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/elsevier-one-sample-affiliation-diagnostic.yml"

# A closed textual contract also catches extra jobs/steps, duplicate YAML keys,
# aliases, alternate trigger spellings and permissions hidden by presence checks.
# No YAML package or unreviewed execution-capable loader is introduced.
REVIEWED_WORKFLOW = """name: One initial-event Elsevier affiliation diagnostic

on:
  pull_request:
    types: [opened]

permissions:
  contents: read

concurrency:
  group: elsevier-affiliation-diagnostic-pr44-initial
  cancel-in-progress: false

jobs:
  private-affiliation-diagnostic:
    if: >-
      github.event_name == 'pull_request' && github.event.action == 'opened' &&
      github.ref == 'refs/pull/44/merge' && github.event.number == 44 &&
      github.run_attempt == 1 && github.repository == 'APReddy-AutoBotz/EmailMonitor' &&
      github.event.pull_request.head.repo.full_name == 'APReddy-AutoBotz/EmailMonitor' &&
      github.event.pull_request.base.repo.full_name == 'APReddy-AutoBotz/EmailMonitor' &&
      github.head_ref == 'feat/elsevier-one-sample-affiliation-diagnostic' &&
      github.base_ref == 'feat/synthetic-affiliation-diagnostic' &&
      github.event.pull_request.base.sha == '93f72166ea246b47f585bf278d681bff8dc2fe79'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          persist-credentials: false
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020
        with:
          node-version: 24.19.0
      - name: Install existing pinned build tools and locked dependencies
        run: |
          python3 -m venv "$RUNNER_TEMP/tooling"
          "$RUNNER_TEMP/tooling/bin/python" -m pip install uv==0.12.23
          echo "$RUNNER_TEMP/tooling/bin" >> "$GITHUB_PATH"
          npm install --global pnpm@11.25.0
          "$RUNNER_TEMP/tooling/bin/uv" sync --project services/backend --locked
      - name: Inspect fixed structure counters and remove private resources
        env:
          PYTHONPATH: services/backend/src
          PYTHONDONTWRITEBYTECODE: "1"
        run: uv run --project services/backend python scripts/packaging/run_private_affiliation_diagnostic_once.py
"""  # noqa: E501

# Local accepted baseline 0245e00 has the independently reviewed PR43 source tree.
# Scope these snapshots to the old one-shot, guest/admission/parser boundaries and
# existing seven synthetic gates. Do not regenerate to accommodate this composer.
# A future intentional change to those boundaries needs its own reviewed scope.
PRESERVED_BOUNDARIES = {
    ".github/workflows/application.yml": (
        "f9d4e0298d8332198b060a89f73dc38cb865f5a6909eef17c4ebf190fa224c39"
    ),
    ".github/workflows/browser-isolation.yml": (
        "b9e5ad950d0c2eadb5d2b37b2aa3ecc49be4fca80f5aa6743952ed29a30ab6bd"
    ),
    ".github/workflows/docs.yml": (
        "794ebde72879cf9ae8e6c70950f83cdff6597fd5f124e11e826cafdd74f6cc3c"
    ),
    ".github/workflows/metadata-packaging.yml": (
        "8bf5d6894e1fdc22604a8508800a4dcee0198e04ff9209a8e2dfd51c3237ae28"
    ),
    ".github/workflows/operator-ui.yml": (
        "a8744a786c32e311eb4739654e41c18beed648123202b20f2b947bdfe5869fde"
    ),
    ".github/workflows/parser-isolation.yml": (
        "2e94d684996e43660caa279248941a8a1f57b860fcf224be11602b8206da5b7b"
    ),
    ".github/workflows/transport-isolation.yml": (
        "8b189da10b7bde3a3b6e8f826a06db595e569dd6c2fc562653165451a00b5b2f"
    ),
    ".github/workflows/elsevier-one-sample.yml": (
        "214f565e4e0ddd373ecf1b9536c40aa259b51bf261d351391593193f1b4bc40b"
    ),
    "scripts/packaging/run_private_sample_once.py": (
        "e90ccb8e94905e496433d2f6891ca93e67d0da07f764fc85e9b3abe6fd5e20fb"
    ),
    "services/backend/src/emailmonitor/parsing/affiliation_diagnostic.py": (
        "b23df4e81f893e28fc1e53170736c7ee7aee5cfad622d6cb352ec07d9935c75f"
    ),
    "services/backend/src/emailmonitor/parsing/affiliation_diagnostic_channel.py": (
        "b0171473fb958f1fb218cc477e30a961d34bd128fe6e26c4c56c3de9ce81bd53"
    ),
    "services/backend/src/emailmonitor/parsing/affiliation_diagnostic_worker.py": (
        "a8fed6d1420eb2b9447dd296a50ed961b813e0ad9be0648f94db2d52693c682d"
    ),
    "services/backend/src/emailmonitor/parsing/private_affiliation_diagnostic.py": (
        "e66451a6264f0dc54ef9ec7f2478d0117c6ed232a4ff5f99bee9b3223732e84b"
    ),
    "services/backend/src/emailmonitor/parsing/private_sample.py": (
        "e19605672a73a478449d59126e9c4de28778ccde9936ade018de6b6204c718d8"
    ),
    "services/backend/src/emailmonitor/parsing/xml_channel.py": (
        "eb293988889f36d86163bb6ff85961780277aa9887bf589c16ac569c7356d7c0"
    ),
    "services/backend/src/emailmonitor/parsing/xml_protocol.py": (
        "db7cd4d74403ec99cb22afe55084fc8feabe469b0e5710de12fc242e48cc510b"
    ),
    "services/backend/src/emailmonitor/parsing/xml_worker.py": (
        "b10c9d9c28ead4b2eaffb0073cd0b8231cbc416cfd17db63efdf9dd88b8fc35c"
    ),
    "services/backend/src/emailmonitor/extraction/sciencedirect.py": (
        "b60ff0fd097001128d1bc4461975c35eff9ea7ab97afbd3822acd4a2aad4df64"
    ),
}


def test_workflow_is_exactly_the_reviewed_closed_initial_event_composition() -> None:
    assert WORKFLOW.read_text(encoding="utf-8") == REVIEWED_WORKFLOW


def test_workflow_requires_every_exact_event_repository_ref_and_attempt_guard() -> None:
    condition = WORKFLOW.read_text().split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
    assert " ".join(condition.split()).split(" && ") == [
        "github.event_name == 'pull_request'",
        "github.event.action == 'opened'",
        "github.ref == 'refs/pull/44/merge'",
        "github.event.number == 44",
        "github.run_attempt == 1",
        "github.repository == 'APReddy-AutoBotz/EmailMonitor'",
        "github.event.pull_request.head.repo.full_name == 'APReddy-AutoBotz/EmailMonitor'",
        "github.event.pull_request.base.repo.full_name == 'APReddy-AutoBotz/EmailMonitor'",
        "github.head_ref == 'feat/elsevier-one-sample-affiliation-diagnostic'",
        "github.base_ref == 'feat/synthetic-affiliation-diagnostic'",
        "github.event.pull_request.base.sha == '93f72166ea246b47f585bf278d681bff8dc2fe79'",
    ]


def test_workflow_only_checks_out_exact_event_head_with_no_persisted_credentials() -> None:
    steps = WORKFLOW.read_text().split("    steps:\n", 1)[1]
    checkout = steps.split("      - uses:", 2)[1]
    assert checkout == (
        " actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683\n"
        "        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
        "          persist-credentials: false\n"
    )
    assert [line.strip() for line in steps.splitlines() if "- uses:" in line] == [
        "- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
        "- uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    ]


def test_workflow_has_only_fixed_pinned_setup_and_one_new_runner_invocation() -> None:
    workflow = WORKFLOW.read_text()
    commands = workflow.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
    assert [line.strip() for line in commands.splitlines()] == [
        'python3 -m venv "$RUNNER_TEMP/tooling"',
        '"$RUNNER_TEMP/tooling/bin/python" -m pip install uv==0.12.23',
        'echo "$RUNNER_TEMP/tooling/bin" >> "$GITHUB_PATH"',
        "npm install --global pnpm@11.25.0",
        '"$RUNNER_TEMP/tooling/bin/uv" sync --project services/backend --locked',
    ]
    assert [line.strip() for line in workflow.splitlines() if "run:" in line] == [
        "run: |",
        "run: uv run --project services/backend python "
        "scripts/packaging/run_private_affiliation_diagnostic_once.py",
    ]
    assert "          node-version: 24.19.0\n" in workflow


def test_workflow_keeps_readonly_serialized_bounded_execution() -> None:
    workflow = WORKFLOW.read_text()
    assert workflow.split("permissions:\n", 1)[1].split("\n\n", 1)[0] == "  contents: read"
    assert workflow.split("concurrency:\n", 1)[1].split("\n\n", 1)[0] == (
        "  group: elsevier-affiliation-diagnostic-pr44-initial\n  cancel-in-progress: false"
    )
    assert "    runs-on: ubuntu-24.04\n    timeout-minutes: 15\n" in workflow
    environment = workflow.split("        env:\n", 1)[1].split("        run:", 1)[0]
    assert environment == (
        '          PYTHONPATH: services/backend/src\n          PYTHONDONTWRITEBYTECODE: "1"\n'
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "push:",
        "synchronize",
        "reopened",
        "workflow_dispatch",
        "workflow_call",
        "schedule:",
        "pull_request_target",
        "secrets",
        "token:",
        "environment:",
        "id-token:",
        "write-all",
        "contents: write",
        "upload-artifact",
        "download-artifact",
        "actions/cache",
        "cache:",
        "cache-",
        "continue-on-error",
        "strategy:",
        "services:",
        "curl ",
        "wget ",
        "raw.githubusercontent.com",
        "run_private_sample_once.py",
        "GITHUB_TOKEN",
        "SSLKEYLOGFILE",
    ],
)
def test_workflow_has_no_extra_trigger_credentials_cache_or_data_sink(forbidden: str) -> None:
    assert forbidden not in WORKFLOW.read_text()


def lifecycle_operator_baseline(content: bytes) -> bytes:
    """Allow exact lifecycle/metadata additions; pin every other original byte."""
    # Permit exactly the scoped, value-free guest metadata; keep the frozen digest.
    additions = (
        b"        id: operator-guest\n",
        b'          EM_GUEST_OUTCOME_REPORT: "true"\n',
        (
            b'      - name: "Operator guest outcome: ${{ '
            b"steps.operator-guest.outputs.guest_outcome "
            b"|| 'unavailable' }}\"\n"
            b"        if: ${{ !cancelled() && steps.operator-guest.outcome != 'skipped' }}\n"
            b"        run: ':'\n"
        ),
    )
    for addition in additions:
        assert content.count(addition) == 1
        content = content.replace(addition, b"")
    original = b"pytest scripts/isolation/test_operator_ui_acceptance.py -v -s\n"
    expanded = (
        b"pytest scripts/isolation/test_operator_ui_acceptance.py "
        b"scripts/isolation/test_operator_lifecycle_acceptance.py -v -s\n"
    )
    assert content.count(expanded) == 1 and content.count(original) == 0
    return content.replace(expanded, original)


def browser_workflow_baseline(content: bytes) -> bytes:
    """Remove exactly the value-free exit receipt, retaining all original bytes."""
    original = (
        b"      - name: Actual sandboxed browser and mediated synthetic gateway checks\n"
        b"        env:\n"
        b"          PYTHONPATH: services/backend/src:tests\n"
        b"        run: uv run --project services/backend python "
        b"scripts/isolation/run_browser_acceptance.py\n"
    )
    wrapped = (
        b"      - name: Actual sandboxed browser and mediated synthetic gateway checks\n"
        b"        id: browser-check\n"
        b"        env:\n"
        b"          PYTHONPATH: services/backend/src:tests\n"
        b"        run: bash scripts/isolation/browser_result.sh uv run "
        b"--project services/backend python scripts/isolation/run_browser_acceptance.py\n"
        b'      - name: "Browser process outcome: ${{ '
        b"steps.browser-check.outputs.browser_outcome || 'unavailable' }}-phase_${{ "
        b"steps.browser-check.outputs.browser_phase || 'unavailable' }}\"\n"
        b"        if: always() && steps.browser-check.outcome == 'failure'\n"
        b'        run: "true"\n'
    )
    assert content.count(wrapped) == 1 and content.count(original) == 0
    return content.replace(wrapped, original)


@pytest.mark.parametrize("relative,expected", PRESERVED_BOUNDARIES.items())
def test_new_composer_preserves_original_one_shot_guest_parser_and_gates(
    relative: str, expected: str
) -> None:
    content = (ROOT / relative).read_bytes()
    if relative == ".github/workflows/operator-ui.yml":
        content = lifecycle_operator_baseline(content)
    if relative == ".github/workflows/browser-isolation.yml":
        content = browser_workflow_baseline(content)
    if relative == ".github/workflows/application.yml":
        # Preserve the original backend bytes, normalizing only its fixed receipt
        # wiring. Additional mandatory jobs/join have executable contract tests.
        suffix = b"\n  outcome_sql:\n"
        backend = b"\n  backend:\n"
        command = b"run_xml_integration.py application-backend\n"
        assert content.count(suffix) == 1
        assert content.count(backend) == 1
        assert content.count(command) == 1
        content = content.split(suffix, 1)[0]
        # Normalize only the explicitly scoped, value-free backend metadata.
        # Keep the original frozen digest and all execution bytes unchanged.
        diagnostic_environment = b'          EM_BACKEND_OUTCOME_REPORT: "true"\n'
        diagnostic_step = (
            b'      - name: "Backend outcome: ${{ steps.tests.outputs.backend_outcome '
            b"|| 'unavailable' }}\"\n"
            b"        if: ${{ !cancelled() && steps.tests.outcome != 'skipped' }}\n"
            b"        run: ':'\n"
        )
        assert content.count(diagnostic_environment) == content.count(diagnostic_step) == 1
        content = content.replace(diagnostic_environment, b"").replace(diagnostic_step, b"")
        outputs = (
            b"    outputs:\n      partition_receipt: ${{ steps.tests.outputs.partition_receipt }}\n"
        )
        step_id = b"        id: tests\n"
        assert content.count(outputs) == content.count(step_id) == 1
        content = content.replace(outputs, b"").replace(step_id, b"")
        assert content.count(backend) == content.count(command) == 1
        content = content.replace(backend, b"\n  scaffold:\n")
        content = content.replace(command, b"run_xml_integration.py application\n")
        # Independently reviewed EM-017 aggregate capacity-only adjustment.
        # Normalize precisely that field; every other original byte stays pinned.
        assert content.count(b"    timeout-minutes: 25\n") == 1
        assert b"timeout-minutes: 20" not in content
        content = content.replace(b"    timeout-minutes: 25\n", b"    timeout-minutes: 20\n")
    assert hashlib.sha256(content).hexdigest() == expected


def test_new_workflow_is_additional_to_all_seven_synthetic_gates_and_original_one_shot() -> None:
    existing = {Path(name).name for name in PRESERVED_BOUNDARIES if name.startswith(".github/")}
    assert len(existing) == 8
    # Later runtime acceptance is additive; every original frozen boundary above
    # remains byte-for-byte unchanged, including both one-shot controls.
    assert {path.name for path in WORKFLOW.parent.glob("*.yml")} == existing | {
        WORKFLOW.name,
        "service-runtime.yml",
    }


@pytest.mark.parametrize("mutation", ["wrapper", "report", "duplicate", "timeout"])
def test_browser_normalization_rejects_unrelated_or_incomplete_changes(mutation: str) -> None:
    content = (ROOT / ".github/workflows/browser-isolation.yml").read_bytes()
    if mutation == "wrapper":
        content = content.replace(b"browser_result.sh", b"unexpected_wrapper.sh")
    elif mutation == "report":
        content = content.replace(b"browser_outcome", b"unexpected_outcome")
    elif mutation == "duplicate":
        content += content[content.index(b"      - name: Actual sandboxed browser") :]
    else:
        content = content.replace(b"timeout-minutes: 20", b"timeout-minutes: 21")
    if mutation == "timeout":
        expected = PRESERVED_BOUNDARIES[".github/workflows/browser-isolation.yml"]
        assert hashlib.sha256(browser_workflow_baseline(content)).hexdigest() != expected
    else:
        with pytest.raises(AssertionError):
            browser_workflow_baseline(content)
