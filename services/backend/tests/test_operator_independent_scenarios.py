"""Owned keyboard acceptance aggregation; pure tests do not run a browser."""

import ast
import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from operator_ui_protocol import (
    OPERATOR_CORE_FLAGS,
    validate_journey,
    validate_operator_aggregate,
    validate_operator_core,
)

JOB = "00000000-0000-4000-8000-000000000003"
ORG = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
TREE = "a" * 40
COMMIT = "b" * 40


def core() -> dict[str, object]:
    return {
        "kind": "result",
        "diagnostic": "synthetic-operator-ui",
        "journey": "operator_core",
        "target_job": JOB,
        "source_tree": TREE,
        "source_commit": COMMIT,
        "network_errno": [101, 101],
        "interfaces": ["lo"],
        "request_count": 400,
        **dict.fromkeys(OPERATOR_CORE_FLAGS, True),
    }


def privacy() -> dict[str, object]:
    return {
        "kind": "result",
        "diagnostic": "synthetic-operator-ui",
        "journey": "operator_privacy",
        "target_job": JOB,
        "source_tree": TREE,
        "source_commit": COMMIT,
        "network_errno": [101, 101],
        "interfaces": ["lo"],
        "request_count": 100,
        "keyboard": True,
        "contact_suppression": True,
        "job_deletion": True,
    }


def setup() -> dict[str, object]:
    return {
        "kind": "bootstrap",
        "origin": "https://app.example.test",
        "journey": "controlled_privacy",
        "cookies": [],
        "assets": {},
        "initial_organization": ORG,
        "other_organization": OTHER,
        "target_job": JOB,
    }


def test_both_complete_scoped_receipts_are_required() -> None:
    validate_operator_core(core(), JOB, COMMIT, TREE)
    validate_operator_aggregate(core(), privacy(), JOB, COMMIT, TREE)
    with pytest.raises(ValueError):
        validate_operator_aggregate(core(), {}, JOB, COMMIT, TREE)
    with pytest.raises(ValueError):
        validate_operator_aggregate({}, privacy(), JOB, COMMIT, TREE)


@pytest.mark.parametrize("flag", OPERATOR_CORE_FLAGS)
def test_every_original_core_flag_is_required(flag: str) -> None:
    item = core()
    del item[flag]
    with pytest.raises(ValueError):
        validate_operator_core(item, JOB, COMMIT, TREE)
    item[flag] = False
    with pytest.raises(ValueError):
        validate_operator_aggregate(item, privacy(), JOB, COMMIT, TREE)


@pytest.mark.parametrize("flag", ["keyboard", "contact_suppression", "job_deletion"])
def test_every_privacy_flag_is_required(flag: str) -> None:
    item = privacy()
    del item[flag]
    with pytest.raises(ValueError):
        validate_operator_aggregate(core(), item, JOB, COMMIT, TREE)
    item[flag] = False
    with pytest.raises(ValueError):
        validate_operator_aggregate(core(), item, JOB, COMMIT, TREE)


@pytest.mark.parametrize("count", [0, 513, -1, True, "100", None])
@pytest.mark.parametrize("which", ["core", "privacy"])
def test_each_guest_must_report_its_own_bounded_numeric_count(count: object, which: str) -> None:
    a, b = core(), privacy()
    (a if which == "core" else b)["request_count"] = count
    with pytest.raises(ValueError):
        validate_operator_aggregate(a, b, JOB, COMMIT, TREE)


@pytest.mark.parametrize("which", ["core", "privacy"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("target_job", OTHER),
        ("source_tree", "b" * 40),
        ("source_commit", "c" * 40),
        ("diagnostic", "private"),
        ("kind", "stage"),
        ("network_errno", [0, 0]),
        ("interfaces", ["eth0"]),
    ],
)
def test_aggregate_refuses_other_job_or_unverified_guest(
    which: str, field: str, value: object
) -> None:
    a, b = core(), privacy()
    (a if which == "core" else b)[field] = value
    with pytest.raises(ValueError):
        validate_operator_aggregate(a, b, JOB, COMMIT, TREE)


def test_two_receipts_cannot_be_the_same_scenario() -> None:
    with pytest.raises(ValueError):
        validate_operator_aggregate(core(), core(), JOB, COMMIT, TREE)
    with pytest.raises(ValueError):
        validate_operator_aggregate(privacy(), privacy(), JOB, COMMIT, TREE)


def test_privacy_bootstrap_is_a_closed_uuid_bound_fixture() -> None:
    value = setup()
    validate_journey(value)
    for field in ("target_job", "initial_organization", "other_organization"):
        invalid = {**value, field: "private"}
        with pytest.raises(ValueError):
            validate_journey(invalid)
    with pytest.raises(ValueError):
        validate_journey({**value, "arbitrary": True})
    with pytest.raises(ValueError):
        validate_journey({**value, "cancel_job": str(UUID(int=5))})
    with pytest.raises(ValueError):
        validate_journey({**value, "other_organization": ORG})
    missing = dict(value)
    del missing["target_job"]
    with pytest.raises(ValueError):
        validate_journey(missing)


def test_moved_privacy_sequence_preserves_every_original_statement() -> None:
    source = Path("scripts/isolation/operator_ui_acceptance.py").read_text()
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    function = next(
        node
        for node in ast.walk(main)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "privacy_journey"
    )
    # Only the fixed capture checkpoint may be added; compare the remaining
    # journey to the exact pre-capture sequence, including all assertions.
    suppression_loop = next(
        node
        for node in function.body
        if isinstance(node, ast.For)
        and any("selected_address" in ast.unparse(item) for item in node.body)
    )
    checkpoints = [
        (index, item)
        for index, item in enumerate(suppression_loop.body)
        if isinstance(item, ast.If) and "capture_business" in ast.unparse(item)
    ]
    assert len(checkpoints) == 1
    index, checkpoint = checkpoints[0]
    assert ast.unparse(checkpoint) == (
        "if capture_enabled and (not commit):\n    await capture_business(page, 'suppression')"
    )
    assert ast.unparse(suppression_loop.body[index - 1]) == (
        "await expect(confirmation).to_contain_text(selected_address)"
    )
    assert ast.unparse(suppression_loop.body[index + 1]).startswith(
        "suppression_phase = 'confirm_suppression'"
    )
    del suppression_loop.body[index]
    # AST hash is the 27-statement sequence from the previously published head,
    # before the required session boundary; line numbers and formatting are excluded.
    moved = ast.Module(body=function.body[1:], type_ignores=[])
    assert len(moved.body) == 27
    digest = hashlib.sha256(ast.dump(moved, include_attributes=False).encode()).hexdigest()
    assert digest == "e1a42336a717c11bc268e813a9384dc2ab7f78c755a5fac36bf82872619aaee7"


def test_host_requires_core_before_second_login_and_aggregate_before_refusal_checks() -> None:
    raw = Path("scripts/isolation/test_operator_ui_acceptance.py").read_text()
    source = ast.unparse(ast.parse(raw))
    core_index = source.index(
        "validate_operator_core(evidence, str(target_job), source_commit, source_tree)"
    )
    login_index = source.index("scenario.login(privacy_owner, 'owner')")
    guest_index = source.index("privacy_evidence = run(app, privacy_setup, control, before_reply)")
    aggregate_index = source.index(
        "validate_operator_aggregate(evidence, privacy_evidence, str(target_job), "
        "source_commit, source_tree)"
    )
    refusal_index = source.index(
        "results.download(org, UUID(str(retained_receipt['export_id'])))", aggregate_index
    )
    assert core_index < login_index < guest_index < aggregate_index < refusal_index
    assert "assert privacy_token != token" in source
    assert "'operator_sessions': 'two_independent_guests'" in source
    assert source.count("operator_source_identity()") >= 5


def test_privacy_guest_switches_from_viewer_scope_before_existing_owner_journey() -> None:
    source = Path("scripts/isolation/operator_ui_acceptance.py").read_text()
    tree = ast.parse(source)
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "setup.get('journey') == 'controlled_privacy'"
    )
    code = ast.unparse(branch)
    assert (
        code.index("values.index(setup['other_organization'])")
        < code.index("name='Synthetic tenant 1'")
        < code.index("await privacy_journey(actual_job)")
    )


@pytest.mark.parametrize(
    "mode", ["clean", "dirty", "invalid", "command_failure", "head_change", "dirty_late"]
)
def test_host_tree_receipt_requires_clean_exact_source(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    import subprocess

    import test_operator_ui_acceptance as host

    counts = {"head": 0, "status": 0}

    def check(command: list[str], **kwargs: object) -> bytes:
        assert kwargs["timeout"] == 10 and kwargs["stderr"] == subprocess.DEVNULL
        if mode == "command_failure":
            raise subprocess.CalledProcessError(1, command, output=b"private data")
        if command[1] == "status":
            counts["status"] += 1
            return (
                b" M private path\n"
                if mode == "dirty" or (mode == "dirty_late" and counts["status"] == 2)
                else b""
            )
        if mode == "invalid":
            return b"not an identity\n"
        if command[-1] == "HEAD":
            counts["head"] += 1
            if mode == "head_change" and counts["head"] == 2:
                return ("c" * 40 + "\n").encode()
        return ((COMMIT if command[-1] == "HEAD" else TREE) + "\n").encode()

    monkeypatch.setattr(subprocess, "check_output", check)
    if mode == "clean":
        assert host.operator_source_identity() == (COMMIT, TREE)
    else:
        with pytest.raises(
            RuntimeError, match="^Clean exact operator source tree required$"
        ) as caught:
            host.operator_source_identity()
        assert caught.value.__suppress_context__
        assert "private" not in str(caught.value)


@pytest.mark.parametrize("source_tree", ["b" * 40, "a" * 39, "private"])
def test_mismatched_or_malformed_source_tree_refuses_combined_evidence(source_tree: str) -> None:
    with pytest.raises(ValueError):
        validate_operator_aggregate(core(), privacy(), JOB, COMMIT, source_tree)


@pytest.mark.parametrize("source_commit", ["c" * 40, "b" * 39, "private"])
def test_mismatched_or_malformed_source_commit_refuses_combined_evidence(
    source_commit: str,
) -> None:
    with pytest.raises(ValueError):
        validate_operator_aggregate(core(), privacy(), JOB, source_commit, TREE)


def test_channel_counter_is_initialized_once_and_never_reset() -> None:
    source = Path("scripts/isolation/operator_ui_acceptance.py").read_text()
    tree = ast.parse(source)
    channel = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Channel"
    )
    assignments = [
        (method.name, node)
        for method in channel.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(method)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "identifier"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    assert len(assignments) == 1 and assignments[0][0] == "__init__"
    assert ast.unparse(assignments[0][1]) == "self.identifier = 0"
    main = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    drain = next(
        node
        for node in ast.walk(main)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "settled_requests"
    )
    assert "while channel.pending or channel.admitted" in ast.unparse(drain)
