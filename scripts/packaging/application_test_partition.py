"""Closed hosted test partitions and a stdlib-only, fail-closed cross-job join."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[2]
OUTCOME = (
    "services/backend/tests/test_job_outcome_investigation_tenant.py::"
    "test_actual_more_than_100_outcomes_have_no_omissions_or_duplicates"
)
RESERVED_SQL = (
    OUTCOME,
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_presence_pages_partition_before_limit_and_item_is_exact"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_item_api_foreign_missing_nonarticle_and_legacy_sql_acl"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_review_rejection_does_not_remove_observed_candidate"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_export_preview_membership_filter_idempotency_and_legacy_defaults"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_second_continuation_uses_original_batch_and_child_authority"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[deletion-preview_create]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[deletion-claim_finish]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[deletion-ready_download]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[retention-preview_create]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[retention-claim_finish]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[retention-ready_download]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[suppression-preview_create]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[suppression-claim_finish]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[suppression-ready_download]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_missing_unsealed_expired_and_mismatched_binding_is_unresolved"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[observed-True-observed_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[partial-True-observed_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[partial-False-unresolved]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[unsupported-False-unresolved]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[no_contact-False-completed_without_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_sql_presence_null_and_inconsistent_profiles_fail_closed"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_ready_artifact_loses_its_source_classification[observed_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_ready_artifact_loses_its_source_classification[completed_without_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_no_contact_and_inherited_contacts_only[False]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_no_contact_and_inherited_contacts_only[True]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[selected_deletion]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[source_deletion]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[retention]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[revocation]"
    ),
)
PROFILES = ("backend", "outcome_sql")
ARGUMENTS = (
    "-c",
    "services/backend/pyproject.toml",
    "--rootdir=.",
    "-o",
    "addopts=",
    "-p",
    "anyio.pytest_plugin",
    "services/backend/tests",
    "tests",
)
OVERRIDES = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONPATH")
COMMON = ("source_tree", "config", "full", "backend", "outcome_sql")


class PartitionRefused(RuntimeError):
    """No selectors, arbitrary commands or partial execution can satisfy a gate."""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def manifest(nodes: Sequence[str]) -> dict[str, str | int]:
    return {"count": len(nodes), "sha256": digest(sorted(nodes))}


def partitions(nodes: Sequence[str]) -> dict[str, list[str]]:
    full = Counter(nodes)
    if (
        not full
        or any(count != 1 for count in full.values())
        or any(full[node] != 1 for node in RESERVED_SQL)
        or any(
            not node.startswith(("services/backend/tests/", "tests/")) or "::" not in node
            for node in full
        )
    ):
        raise PartitionRefused("application_collection_refused")
    result = {
        "backend": [node for node in nodes if node not in RESERVED_SQL],
        "outcome_sql": [node for node in nodes if node in RESERVED_SQL],
    }
    backend, outcome = (Counter(result[key]) for key in PROFILES)
    if not backend or backend & outcome or backend + outcome != full:
        raise PartitionRefused("application_partition_refused")
    return result


def source_tree() -> str:
    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", *arguments], cwd=ROOT, timeout=10).decode().strip()

    if git("status", "--porcelain", "--untracked-files=all"):
        raise PartitionRefused("application_source_dirty")
    tree = git("rev-parse", "HEAD^{tree}")
    if not re.fullmatch(r"[a-f0-9]{40}", tree):
        raise PartitionRefused("application_source_refused")
    return tree


def configuration() -> str:
    return digest(
        {
            "arguments": ARGUMENTS,
            "autoload": False,
            "files": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ("services/backend/pyproject.toml", "services/backend/uv.lock")
            },
        }
    )


class PartitionProof:
    def __init__(self, profile: str) -> None:
        if profile not in PROFILES:
            raise PartitionRefused("application_profile_refused")
        self.profile = profile
        self.discovered: list[str] = []
        self.full: list[str] = []
        self.assigned: dict[str, list[str]] = {}
        self.deselected: list[str] = []
        self.reports: Counter[tuple[str, str, str]] = Counter()
        self.collection_complete = False
        self.invalid = False

    def pytest_configure(self, config: pytest.Config) -> None:
        if config.invocation_params.args != ARGUMENTS:
            raise PartitionRefused("application_pytest_arguments_refused")

    def pytest_itemcollected(self, item: pytest.Item) -> None:
        self.discovered.append(item.nodeid)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.outcome != "passed":
            self.invalid = True

    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        self.full = [item.nodeid for item in items]
        if self.assigned or Counter(self.full) != Counter(self.discovered) or self.deselected:
            raise PartitionRefused("application_collection_changed")
        self.assigned = partitions(self.full)
        selected = set(self.assigned[self.profile])
        excluded = [item for item in items if item.nodeid not in selected]
        items[:] = [item for item in items if item.nodeid in selected]
        config.hook.pytest_deselected(items=excluded)

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if (
            not self.assigned
            or Counter(item.nodeid for item in session.items)
            != Counter(self.assigned[self.profile])
            or Counter(self.deselected) != Counter(self.assigned[self.other])
            or Counter(self.discovered) != Counter(self.full)
        ):
            raise PartitionRefused("application_selection_changed")
        self.collection_complete = True

    @property
    def other(self) -> str:
        return "outcome_sql" if self.profile == "backend" else "backend"

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.reports[report.nodeid, report.when, report.outcome] += 1
        if hasattr(report, "wasxfail"):
            self.invalid = True

    def receipt(self, code: int, tree: str, config: str) -> dict[str, Any]:
        expected = Counter(
            (node, phase, "passed")
            for node in self.assigned.get(self.profile, [])
            for phase in ("setup", "call", "teardown")
        )
        if code != 0 or self.invalid or not self.collection_complete or self.reports != expected:
            raise PartitionRefused("application_execution_incomplete")
        return {
            "schema": 1,
            "profile": self.profile,
            "source_tree": tree,
            "config": config,
            "full": manifest(self.full),
            **{profile: manifest(self.assigned[profile]) for profile in PROFILES},
            "executed": manifest(self.assigned[self.profile]),
            "deselected": manifest(self.deselected),
            "skipped": 0,
        }


def run(profile: str, environment: Mapping[str, str]) -> dict[str, Any]:
    if any(environment.get(key) for key in OVERRIDES):
        raise PartitionRefused("application_pytest_override_refused")
    proof = PartitionProof(profile)
    tree, config = source_tree(), configuration()
    # Keep exactly the existing pinned AnyIO plugin, without ambient entry points.
    # Set before importing pytest; no user-supplied argv reaches pytest.main.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest

    os.chdir(ROOT)
    code = pytest.main(list(ARGUMENTS), plugins=[proof])
    if source_tree() != tree or configuration() != config:
        raise PartitionRefused("application_source_changed")
    return proof.receipt(int(code), tree, config)


def decode_receipt(raw: str, profile: str) -> dict[str, Any]:
    if len(raw) > 4096:
        raise PartitionRefused("application_receipt_refused")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PartitionRefused("application_receipt_refused")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "profile", *COMMON, "executed", "deselected", "skipped"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["profile"] != profile
        or type(value["skipped"]) is not int
        or value["skipped"] != 0
    ):
        raise PartitionRefused("application_receipt_refused")
    for key, length in (("source_tree", 40), ("config", 64)):
        if not isinstance(value[key], str) or not re.fullmatch(
            rf"[a-f0-9]{{{length}}}", value[key]
        ):
            raise PartitionRefused("application_receipt_refused")
    for key in ("full", *PROFILES, "executed", "deselected"):
        entry = value[key]
        if (
            not isinstance(entry, dict)
            or set(entry) != {"count", "sha256"}
            or type(entry["count"]) is not int
            or not 0 < entry["count"] < 1_000_000
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
        ):
            raise PartitionRefused("application_receipt_refused")
    other = "outcome_sql" if profile == "backend" else "backend"
    if (
        value["outcome_sql"] != manifest(RESERVED_SQL)
        or value["full"]["count"] != value["backend"]["count"] + value["outcome_sql"]["count"]
        or value["executed"] != value[profile]
        or value["deselected"] != value[other]
    ):
        raise PartitionRefused("application_receipt_refused")
    return value


def join(environment: Mapping[str, str]) -> None:
    if any(
        environment.get(key) != "success"
        for key in ("BACKEND_RESULT", "OUTCOME_SQL_RESULT", "STATIC_RESULT")
    ):
        raise PartitionRefused("application_dependency_failed")
    backend = decode_receipt(environment.get("BACKEND_RECEIPT", ""), "backend")
    outcome = decode_receipt(environment.get("OUTCOME_SQL_RECEIPT", ""), "outcome_sql")
    if (
        any(backend[key] != outcome[key] for key in COMMON)
        or backend["source_tree"] != source_tree()
        or backend["config"] != configuration()
    ):
        raise PartitionRefused("application_receipts_differ")


def main(arguments: Sequence[str]) -> int:
    try:
        if len(arguments) != 1:
            raise PartitionRefused("application_arguments_refused")
        if arguments[0] == "join":
            join(os.environ)
        elif arguments[0] in PROFILES:
            receipt = run(arguments[0], os.environ)
            encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            output = os.environ.get("GITHUB_OUTPUT")
            if not output:
                raise PartitionRefused("application_output_missing")
            with Path(output).open("a") as stream:
                stream.write("partition_receipt=" + encoded + "\n")
            print("APPLICATION_PARTITION_VERIFIED " + encoded)
        else:
            raise PartitionRefused("application_arguments_refused")
        return 0
    except (PartitionRefused, ValueError, OSError, subprocess.SubprocessError):
        print("APPLICATION_PARTITION_REFUSED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
