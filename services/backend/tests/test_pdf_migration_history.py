"""Pure history-delta assertions; never a substitute for guarded migration/restore CI."""

import copy
import hashlib
import json
from typing import Any

import pytest
from emailmonitor.extraction.pdf_fixture import pdf_bytes
from test_service_migration_compatibility import (
    PDF_MIGRATION_DIGESTS,
    assert_pdf_upgrade_history,
)


def histories() -> tuple[dict[str, list[tuple[object, ...]]], dict[str, list[tuple[object, ...]]]]:
    source: dict[str, Any] = {
        "source_id": "synthetic-publisher",
        "execution_mode": "fixture",
        "enabled": True,
        "revision": 1,
        "allowed_operations": [
            "fetch_html",
            "extract_contacts",
            "retain_excerpt",
            "export_contacts",
        ],
        "support": {
            "pdf_supported": False,
            "unrelated": {"preserve": ["literal"]},
            "routes_by_operation": {
                op: ["/article-a.html"]
                for op in ("fetch_html", "extract_contacts", "retain_excerpt", "export_contacts")
            },
        },
    }
    other = {"source_id": "other", "execution_mode": "disabled", "enabled": False}
    before: dict[str, list[tuple[object, ...]]] = {
        "source_catalog": [(json.dumps(source),), (json.dumps(other),)],
        "jobs": [("unchanged job bytes",)],
        "source_policies": [("unchanged approved policy bytes",)],
        "sessions": [("unchanged session bytes",)],
    }
    after = copy.deepcopy(before)
    source["allowed_operations"].append("parse_fixture_pdf")
    support = source["support"]
    support["pdf_fixture_opt_in"] = True
    support["authored_pdf_digests"] = {
        "https://synthetic.publisher.example/" + name: digest
        for name, digest in PDF_MIGRATION_DIGESTS.items()
    }
    paths = ["/" + name for name in PDF_MIGRATION_DIGESTS]
    support["routes_by_operation"]["parse_fixture_pdf"] = paths.copy()
    for operation in ("extract_contacts", "retain_excerpt", "export_contacts"):
        support["routes_by_operation"][operation] += paths
    after["source_catalog"][0] = (json.dumps(source),)
    return before, after


def test_exact_pdf_delta_preserves_input_and_json_object_order_is_irrelevant() -> None:
    before, after = histories()
    original = copy.deepcopy(before)
    after["source_catalog"] = [
        (json.dumps(json.loads(row[0]), sort_keys=True),)  # type: ignore[arg-type]
        for row in reversed(after["source_catalog"])
    ]
    assert_pdf_upgrade_history(before, after)
    assert before == original
    assert len(PDF_MIGRATION_DIGESTS) == 9
    for name, expected in PDF_MIGRATION_DIGESTS.items():
        assert hashlib.sha256(pdf_bytes(name)).hexdigest() == expected


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_delta",
        "extra_operation",
        "duplicate_operation",
        "live_fetch",
        "enabled",
        "revision",
        "mode",
        "external_pdf",
        "extra_support",
        "unrelated_support",
        "flag_false",
        "flag_integer",
        "digest_changed",
        "digest_missing",
        "digest_extra",
        "route_extra",
        "route_missing",
        "route_reordered",
        "existing_route_removed",
        "html_route_added",
        "other_source",
        "source_added",
        "source_removed",
        "duplicate_source",
        "jobs",
        "source_policies",
        "sessions",
        "table_added",
        "table_removed",
    ],
)
def test_pdf_delta_refuses_every_unrelated_or_incomplete_change(mutation: str) -> None:
    before, after = histories()
    source = json.loads(str(after["source_catalog"][0][0]))
    support = source["support"]
    routes = support["routes_by_operation"]
    if mutation == "missing_delta":
        after = copy.deepcopy(before)
    elif mutation in {"extra_operation", "duplicate_operation", "live_fetch"}:
        source["allowed_operations"].append(
            {
                "extra_operation": "browser",
                "duplicate_operation": "parse_fixture_pdf",
                "live_fetch": "fetch_pdf",
            }[mutation]
        )
    elif mutation in {"enabled", "revision", "mode"}:
        source[{"mode": "execution_mode"}.get(mutation, mutation)] = {
            "enabled": False,
            "revision": 2,
            "mode": "live",
        }[mutation]
    elif mutation == "external_pdf":
        support["pdf_supported"] = True
    elif mutation == "extra_support":
        support["new_key"] = True
    elif mutation == "unrelated_support":
        support["unrelated"]["preserve"] = []
    elif mutation in {"flag_false", "flag_integer"}:
        support["pdf_fixture_opt_in"] = False if mutation == "flag_false" else 1
    elif mutation.startswith("digest_"):
        key = "https://synthetic.publisher.example/article-a.pdf"
        if mutation == "digest_changed":
            support["authored_pdf_digests"][key] = "0" * 64
        elif mutation == "digest_missing":
            del support["authored_pdf_digests"][key]
        else:
            support["authored_pdf_digests"][key + ".extra"] = "0" * 64
    elif mutation == "route_extra":
        routes["parse_fixture_pdf"].append("/unknown.pdf")
    elif mutation == "route_missing":
        routes["retain_excerpt"].pop()
    elif mutation == "route_reordered":
        routes["export_contacts"].reverse()
    elif mutation == "existing_route_removed":
        routes["extract_contacts"].pop(0)
    elif mutation == "html_route_added":
        routes["fetch_html"].append("/article-a.pdf")
    elif mutation == "other_source":
        after["source_catalog"][1] = ('{"source_id":"other","enabled":true}',)
    elif mutation == "source_added":
        after["source_catalog"].append(('{"source_id":"new"}',))
    elif mutation == "source_removed":
        after["source_catalog"].pop()
    elif mutation == "duplicate_source":
        after["source_catalog"].append(after["source_catalog"][1])
    elif mutation in {"jobs", "source_policies", "sessions"}:
        after[mutation] = [("changed",)]
    elif mutation == "table_added":
        after["extra"] = []
    elif mutation == "table_removed":
        del after["jobs"]
    if mutation != "missing_delta":
        after["source_catalog"][0] = (json.dumps(source),)
    with pytest.raises(AssertionError):
        assert_pdf_upgrade_history(before, after)
