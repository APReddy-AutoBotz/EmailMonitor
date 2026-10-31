"""Hosted partition completeness is enforced at collection, execution and join."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import application_test_partition as partition
import pytest

OTHER = "tests/test_other.py::test_other"
FULL = [*partition.RESERVED_SQL, *partition.CAPACITY_EXTRA, *partition.CONTEXT_SQL, OTHER]
TREE = "a" * 40
CONFIG = "b" * 64


def completed(profile: str) -> partition.PartitionProof:
    proof = partition.PartitionProof(profile)
    proof.discovered = proof.full = FULL.copy()
    proof.assigned = partition.partitions(FULL)
    proof.deselected = proof.excluded.copy()
    proof.collection_complete = True
    proof.reports = Counter(
        (node, phase, "passed")
        for node in proof.assigned[profile]
        for phase in ("setup", "call", "teardown")
    )
    return proof


def receipts() -> dict[str, str]:
    return {
        "BACKEND_RESULT": "success",
        "OUTCOME_SQL_RESULT": "success",
        "CAPACITY_SQL_RESULT": "success",
        "STATIC_RESULT": "success",
        **{
            profile.upper() + "_RECEIPT": json.dumps(completed(profile).receipt(0, TREE, CONFIG))
            for profile in partition.PROFILES
        },
    }


@pytest.mark.parametrize(
    "nodes",
    [
        [],
        [OTHER],
        [partition.OUTCOME],
        [*FULL, OTHER],
        [*FULL, partition.OUTCOME],
        [partition.OUTCOME + "[new]", OTHER],
        [*FULL, "outside/test_new.py::test_unknown"],
    ],
)
def test_missing_renamed_duplicate_or_unclassified_collection_fails(nodes: list[str]) -> None:
    with pytest.raises(partition.PartitionRefused):
        partition.partitions(nodes)


@pytest.mark.parametrize("node", partition.RESERVED_SQL)
@pytest.mark.parametrize("mutation", ["missing", "renamed", "duplicate"])
def test_each_reserved_sql_node_is_required_exactly_once(node: str, mutation: str) -> None:
    nodes = FULL.copy()
    if mutation == "missing":
        nodes.remove(node)
    elif mutation == "renamed":
        nodes[nodes.index(node)] = node + "[renamed]"
    else:
        nodes.append(node)
    with pytest.raises(partition.PartitionRefused):
        partition.partitions(nodes)


def test_measured_sql_move_is_explicit_and_preserves_unique_membership() -> None:
    moved = partition.MEASURED_SQL
    assert len(moved) == len(set(moved)) == 45
    assert sum("/test_association_tenant.py::" in node for node in moved) == 30
    assert sum("/test_retained_paper_identity_tenant.py::" in node for node in moved) == 15
    assert not set(moved) & set(
        (
            *partition.RETAINED_SQL,
            *partition.PDF_ACCEPTANCE,
            *partition.SERVICE_SQL,
            *partition.TIMING_SQL,
        )
    )
    assigned = partition.partitions(FULL)
    assert all(assigned["capacity_sql"].count(node) == 1 for node in moved)
    assert not set(moved) & set(assigned["backend"])


def test_each_new_capacity_node_is_required_once_and_refuses_collision() -> None:
    assert len(partition.CAPACITY_EXTRA) == len(set(partition.CAPACITY_EXTRA)) == 120
    assert not set(partition.CAPACITY_EXTRA) & set(partition.RESERVED_SQL)
    for node in partition.CAPACITY_EXTRA:
        for mutation in ("missing", "renamed", "duplicate"):
            nodes = FULL.copy()
            if mutation == "missing":
                nodes.remove(node)
            elif mutation == "renamed":
                nodes[nodes.index(node)] = node + "[renamed]"
            else:
                nodes.append(node)
            with pytest.raises(partition.PartitionRefused):
                partition.partitions(nodes)


def test_context_sql_inventory_is_required_once_and_cannot_be_skipped() -> None:
    assert len(partition.CONTEXT_SQL) == len(set(partition.CONTEXT_SQL)) == 13
    assert not set(partition.CONTEXT_SQL) & set(partition.RESERVED_SQL)
    assert not set(partition.CONTEXT_SQL) & set(partition.CAPACITY_EXTRA)
    result = partition.partitions(FULL)
    for node in partition.CONTEXT_SQL:
        assert result["capacity_sql"].count(node) == 1
        assert node not in result["backend"] and node not in result["outcome_sql"]
        for mutation in ("missing", "duplicate"):
            changed = FULL.copy()
            changed.remove(node) if mutation == "missing" else changed.append(node)
            with pytest.raises(partition.PartitionRefused):
                partition.partitions(changed)


def test_new_tests_are_never_omitted_from_exact_disjoint_multiset_union() -> None:
    nodes = [*FULL, "services/backend/tests/test_new.py::test_new[variant]"]
    result = partition.partitions(nodes)
    assert result["outcome_sql"] == [
        n for n in partition.RESERVED_SQL if n not in partition.CAPACITY_SQL
    ]
    assert result["capacity_sql"] == list(partition.CAPACITY_SQL)
    assert result["backend"] == [OTHER, nodes[-1]]
    counts = [Counter(result[p]) for p in partition.PROFILES]
    assert all(not counts[i] & counts[j] for i in range(3) for j in range(i + 1, 3))
    assert sum(counts, Counter()) == Counter(nodes)
    assert partition.manifest(nodes) == partition.manifest(list(reversed(nodes)))
    assert partition.manifest(nodes) != partition.manifest([*nodes, OTHER])


@pytest.mark.parametrize("profile", partition.PROFILES)
@pytest.mark.parametrize(
    "mutation",
    [
        "code",
        "skip",
        "fail",
        "missing",
        "duplicate",
        "extra",
        "xfail",
        "collection",
        "setup",
        "teardown",
    ],
)
def test_receipt_requires_exact_successful_execution(profile: str, mutation: str) -> None:
    proof = completed(profile)
    node = proof.assigned[profile][0]
    code = 0
    if mutation == "code":
        code = 1
    elif mutation in {"skip", "fail"}:
        proof.reports[node, "call", "skipped" if mutation == "skip" else "failed"] += 1
    elif mutation in {"missing", "setup", "teardown"}:
        del proof.reports[node, "call" if mutation == "missing" else mutation, "passed"]
    elif mutation == "duplicate":
        proof.reports[node, "call", "passed"] += 1
    elif mutation == "extra":
        proof.reports["tests/test_unassigned.py::test_extra", "call", "passed"] += 1
    elif mutation == "xfail":
        proof.invalid = True
    else:
        proof.collection_complete = False
    with pytest.raises(partition.PartitionRefused, match="application_execution_incomplete"):
        proof.receipt(code, TREE, CONFIG)


@pytest.mark.parametrize("mutation", ["selected", "deselected", "discovered"])
def test_collection_finish_detects_late_selection_changes(mutation: str) -> None:
    proof = completed("backend")
    items = [SimpleNamespace(nodeid=OTHER)]
    if mutation == "selected":
        items.append(SimpleNamespace(nodeid=partition.OUTCOME))
    elif mutation == "deselected":
        proof.deselected.append(partition.OUTCOME)
    else:
        proof.discovered = [OTHER]
    with pytest.raises(partition.PartitionRefused, match="application_selection_changed"):
        proof.pytest_collection_finish(SimpleNamespace(items=items))  # type: ignore[arg-type]


@pytest.mark.parametrize("key", partition.OVERRIDES)
def test_environment_cannot_inject_selectors_or_plugins(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setattr(partition, "source_tree", lambda: pytest.fail("source access"))
    with pytest.raises(partition.PartitionRefused, match="application_pytest_override_refused"):
        partition.run("backend", {key: "injected"})


@pytest.mark.parametrize("arguments", [[], [""], ["-k"], ["backend", "-k", "x"], [OTHER]])
def test_entrypoint_cannot_run_arbitrary_commands_or_selectors(arguments: list[str]) -> None:
    assert partition.main(arguments) == 1


@pytest.mark.parametrize("profile", partition.PROFILES)
def test_join_accepts_only_complete_bound_receipts(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    environment = receipts()
    monkeypatch.setattr(partition, "source_tree", lambda: TREE)
    monkeypatch.setattr(partition, "configuration", lambda: CONFIG)
    partition.join(environment)
    decoded = partition.decode_receipt(environment[profile.upper() + "_RECEIPT"], profile)
    assert decoded["executed"] == decoded[profile]
    assert decoded["deselected"] == decoded["excluded_" + profile]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "malformed",
        "duplicate_key",
        "extra_key",
        "bool",
        "skip",
        "role",
        "count",
        "hash",
        "full",
        "source",
        "config",
        "executed",
        "deselected",
        "dedicated",
        "oversize",
    ],
)
def test_join_rejects_incomplete_mismatched_or_malformed_receipts(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    environment = receipts()
    monkeypatch.setattr(partition, "source_tree", lambda: TREE)
    monkeypatch.setattr(partition, "configuration", lambda: CONFIG)
    value = json.loads(environment["OUTCOME_SQL_RECEIPT"])
    if mutation == "extra_key":
        value["extra"] = 1
    elif mutation == "bool":
        value["skipped"] = False
    elif mutation == "skip":
        value["skipped"] = 1
    elif mutation == "role":
        value["profile"] = "backend"
    elif mutation == "count":
        value["full"]["count"] += 1
    elif mutation == "hash":
        value["full"]["sha256"] = "invalid"
    elif mutation == "full":
        value["full"]["sha256"] = "f" * 64
    elif mutation == "source":
        value["source_tree"] = "c" * 40
    elif mutation == "config":
        value["config"] = "d" * 64
    elif mutation in {"executed", "deselected"}:
        value[mutation]["sha256"] = "e" * 64
    elif mutation == "dedicated":
        value["outcome_sql"] = partition.manifest([OTHER])
        value["executed"] = value["outcome_sql"]
    raw = json.dumps(value)
    raw = {
        "missing": "",
        "malformed": "[",
        "duplicate_key": raw[:-1] + ',"schema":1}',
        "oversize": " " * 4097,
    }.get(mutation, raw)
    environment["OUTCOME_SQL_RECEIPT"] = raw
    with pytest.raises((partition.PartitionRefused, ValueError)):
        partition.join(environment)


@pytest.mark.parametrize("node", partition.RESERVED_SQL)
def test_receipt_cannot_replace_any_reserved_node_with_same_count(node: str) -> None:
    profile = "capacity_sql" if node in partition.CAPACITY_SQL else "outcome_sql"
    proof = completed(profile)
    value = proof.receipt(0, TREE, CONFIG)
    changed = proof.assigned[profile].copy()
    changed[changed.index(node)] = OTHER
    value[profile] = value["executed"] = partition.manifest(changed)
    with pytest.raises(partition.PartitionRefused, match="application_receipt_refused"):
        partition.decode_receipt(json.dumps(value), profile)


def test_third_receipt_cannot_replace_any_capacity_node_with_same_count() -> None:
    for node in partition.CAPACITY_SQL:
        proof = completed("capacity_sql")
        value = proof.receipt(0, TREE, CONFIG)
        changed = proof.assigned["capacity_sql"].copy()
        changed[changed.index(node)] = OTHER
        value["capacity_sql"] = value["executed"] = partition.manifest(changed)
        with pytest.raises(partition.PartitionRefused, match="application_receipt_refused"):
            partition.decode_receipt(json.dumps(value), "capacity_sql")


@pytest.mark.parametrize(
    "mutation", ["missing", "source", "config", "skipped", "deselected", "swapped"]
)
def test_join_rejects_bad_third_receipt(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    environment = receipts()
    monkeypatch.setattr(partition, "source_tree", lambda: TREE)
    monkeypatch.setattr(partition, "configuration", lambda: CONFIG)
    value = json.loads(environment["CAPACITY_SQL_RECEIPT"])
    if mutation == "source":
        value["source_tree"] = "c" * 40
    elif mutation == "config":
        value["config"] = "d" * 64
    elif mutation == "skipped":
        value["skipped"] = 1
    elif mutation == "deselected":
        value["deselected"]["sha256"] = "e" * 64
    raw = json.dumps(value)
    if mutation == "missing":
        raw = ""
    elif mutation == "swapped":
        raw = environment["BACKEND_RECEIPT"]
    environment["CAPACITY_SQL_RECEIPT"] = raw
    with pytest.raises((partition.PartitionRefused, ValueError)):
        partition.join(environment)


@pytest.mark.parametrize("changed", ["source_tree", "configuration"])
def test_join_also_binds_receipts_to_its_own_checkout(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    monkeypatch.setattr(partition, "source_tree", lambda: TREE)
    monkeypatch.setattr(partition, "configuration", lambda: CONFIG)
    monkeypatch.setattr(partition, changed, lambda: "e" * (40 if changed == "source_tree" else 64))
    with pytest.raises(partition.PartitionRefused, match="application_receipts_differ"):
        partition.join(receipts())


def test_join_refusal_works_without_site_packages() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(Path(partition.__file__)), "join"],
        env={},
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr == b"APPLICATION_PARTITION_REFUSED\n"


@pytest.mark.parametrize("profile", partition.PROFILES)
@pytest.mark.parametrize("mutation", ["none", "skip", "xfail", "fail", "filter", "duplicate"])
def test_actual_pytest_lifecycle_enforces_assigned_nodes_and_zero_skips(
    tmp_path: Path, profile: str, mutation: str
) -> None:
    directory = tmp_path / "services/backend/tests"
    directory.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (directory.parent / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    body = {
        "skip": "pytest.skip('fixture')",
        "xfail": "pytest.xfail('fixture')",
        "fail": "assert False",
    }.get(mutation, "assert True")
    functions: dict[str, dict[str, list[str]]] = {}
    for node in (*partition.RESERVED_SQL, *partition.CAPACITY_EXTRA, *partition.CONTEXT_SQL):
        filename, function = node.split("::", 1)
        name, _, variant = function.partition("[")
        functions.setdefault(filename, {}).setdefault(name, [])
        if variant:
            functions[filename][name].append(variant[:-1])
    for filename, cases in functions.items():
        source = "import pytest\n"
        for name, variants in cases.items():
            if variants:
                source += f"@pytest.mark.parametrize('case', {variants!r}, ids={variants!r})\n"
            argument = "case" if variants else ""
            source += f"def {name}({argument}):\n    {body}\n"
        (tmp_path / filename).write_text(source)
    # Exercise the same explicit AnyIO plugin used by the full backend.
    (tmp_path / "tests/test_other.py").write_text(
        "import pytest\n@pytest.fixture\ndef anyio_backend(): return 'asyncio'\n"
        f"@pytest.mark.anyio\nasync def test_other():\n    {body}\n"
    )
    script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import application_test_partition as p
import pytest
proof = p.PartitionProof(sys.argv[2])
arguments = list(p.ARGUMENTS)
if sys.argv[3] == 'filter': arguments += ['-k', 'test_other']
if sys.argv[3] == 'duplicate': arguments += ['--keep-duplicates', 'tests/test_other.py']
code = pytest.main(arguments, plugins=[proof])
try:
    print('RECEIPT=' + json.dumps(proof.receipt(int(code), 'a'*40, 'b'*64)))
except p.PartitionRefused:
    raise SystemExit(1)
"""
    environment = {
        key: value for key, value in os.environ.items() if key not in partition.OVERRIDES
    }
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(partition.__file__).parent), profile, mutation],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if mutation == "none":
        assert result.returncode == 0, result.stdout + result.stderr
        value: dict[str, Any] = json.loads(result.stdout.split("RECEIPT=", 1)[1])
        assert value["executed"] == partition.manifest(partition.partitions(FULL)[profile])
        assert value["skipped"] == 0
    else:
        assert result.returncode != 0 and "RECEIPT=" not in result.stdout


@pytest.mark.parametrize("outcome", ["skipped", "failed"])
def test_collection_skip_or_error_prevents_receipt(outcome: str) -> None:
    proof = completed("backend")
    proof.pytest_collectreport(SimpleNamespace(outcome=outcome))  # type: ignore[arg-type]
    with pytest.raises(partition.PartitionRefused):
        proof.receipt(0, TREE, CONFIG)


@pytest.mark.parametrize("mutation", ["removed", "deselected", "repeat"])
def test_external_preselection_or_repeated_classification_refuses(mutation: str) -> None:
    proof = partition.PartitionProof("backend")
    proof.discovered = FULL.copy()
    items = [SimpleNamespace(nodeid=node) for node in FULL]
    if mutation == "removed":
        items.pop()
    elif mutation == "deselected":
        proof.deselected = [OTHER]
    else:
        proof.assigned = partition.partitions(FULL)
    with pytest.raises(partition.PartitionRefused, match="application_collection_changed"):
        proof.pytest_collection_modifyitems(None, items)  # type: ignore[arg-type]


@pytest.mark.parametrize("mutation", ["none", "source", "config", "failure"])
def test_runner_binds_fixed_pytest_config_and_rechecks_source_after_execution(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    trees = iter([TREE, "c" * 40 if mutation == "source" else TREE])
    configs = iter([CONFIG, "d" * 64 if mutation == "config" else CONFIG])
    monkeypatch.setattr(partition, "source_tree", lambda: next(trees))
    monkeypatch.setattr(partition, "configuration", lambda: next(configs))
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.chdir(partition.ROOT)

    def execute(arguments: list[str], plugins: list[partition.PartitionProof]) -> int:
        assert arguments == list(partition.ARGUMENTS)
        assert os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert Path.cwd() == partition.ROOT
        assert len(plugins) == 1 and plugins[0].profile == "backend"
        plugins[0].__dict__.update(completed("backend").__dict__)
        return 1 if mutation == "failure" else 0

    monkeypatch.setattr(pytest, "main", execute)
    if mutation == "none":
        assert partition.run("backend", {})["executed"] == partition.manifest([OTHER])
    else:
        with pytest.raises(partition.PartitionRefused):
            partition.run("backend", {})


@pytest.mark.parametrize("success", [True, False])
def test_output_is_one_bounded_receipt_only_after_verified_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, success: bool
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def execute(*args: object) -> dict[str, Any]:
        if not success:
            raise partition.PartitionRefused("incomplete")
        return completed("backend").receipt(0, TREE, CONFIG)

    monkeypatch.setattr(partition, "run", execute)
    assert partition.main(["backend"]) == (0 if success else 1)
    if success:
        lines = output.read_text().splitlines()
        assert len(lines) == 1 and lines[0].startswith("partition_receipt=")
        partition.decode_receipt(lines[0].split("=", 1)[1], "backend")
    else:
        assert not output.exists()


def test_receipts_cannot_be_swapped(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = receipts()
    environment["BACKEND_RECEIPT"], environment["OUTCOME_SQL_RECEIPT"] = (
        environment["OUTCOME_SQL_RECEIPT"],
        environment["BACKEND_RECEIPT"],
    )
    with pytest.raises(partition.PartitionRefused):
        partition.join(environment)
