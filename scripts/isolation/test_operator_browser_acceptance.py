"""Normal authenticated UI and registered RabbitMQ task, not manual journey execution."""

import asyncio
import csv
import hashlib
import io
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import httpx
import pytest
from api_client import APIClient
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Contact, ExportState, Filters
from emailmonitor.results.service import Results
from emailmonitor.runtime.assembly import RuntimeBundle, owned_test_runtime
from emailmonitor.runtime.assembly import TestRuntimeConfig as RuntimeConfig
from emailmonitor.runtime.publisher import TestPublisherConfig as PublisherConfig
from emailmonitor.runtime.publisher import publish_once
from operator_browser_worker import browser_worker
from operator_ui_protocol import RequestFrame, asset_manifest
from run_operator_ui_acceptance import run
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import config, wait_for
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from test_transport_acceptance import configure, snapshot
from test_transport_acceptance import topology as topology
from transport_manifest import ENDPOINTS, HOST
from transport_topology import Topology

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def browser_topology(topology: Topology) -> Iterator[Topology]:
    # Dedicated module topology; one precreated guest and one gateway owner.
    topology.browser()
    yield topology


def test_actual_browser_tooltip_operator_ui(browser_topology: Topology, scenario: Scenario) -> None:
    if os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true":
        pytest.fail("Required controlled operator acceptance marker missing")
    cfg = RuntimeConfig(
        settings=SETTINGS.model_copy(update={"identity_stub": True}),
        runtime_database_url=os.environ["EM_TEST_DATABASE_URL"],
        authentication_database_url=os.environ["EM_TEST_AUTH_DATABASE_URL"],
    )
    with owned_test_runtime(cfg, scenario.foundation.provider) as runtime:
        assert runtime.api_database is not scenario.foundation.database
        assert runtime.publisher_database is not runtime.api_database
        _browser_operator_journey(browser_topology, scenario, runtime)
    with APIClient(runtime.app, ORIGIN) as closed:
        assert closed.get("/healthz").status_code == 503
    print(
        json.dumps({"owned_test_runtime_closed": True, "separate_api_publisher_pools": True}),
        flush=True,
    )


def _browser_operator_journey(
    topology: Topology,
    scenario: Scenario,
    runtime: RuntimeBundle,
    *,
    keyword: bool = False,
) -> None:
    url = "https://synthetic.publisher.example/tooltip.html"
    expected_articles, expected_tickets = (4 if keyword else 1), 2
    expected_addresses = {"elena.park@example.org"}
    if keyword:
        expected_addresses |= {
            "alex.chen@example.org",
            "ravi.das@example.org",
            "noor.ibrahim@example.org",
        }
    journey = "controlled_keyword_browser" if keyword else "controlled_browser"
    configure(topology)
    browser_evidence: list[dict[str, Any]] = []
    app = runtime.app
    org, other = scenario.organizations
    with APIClient(app, ORIGIN) as owner, scenario.client() as other_owner:
        csrf = scenario.login(other_owner, "owner_b")
        assert (
            other_owner.post(
                f"/api/v1/organizations/{other}/members",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={
                    "identity_id": str(scenario.identities["owner"]),
                    "role": "viewer",
                },
            ).status_code
            == 201
        )
        assert other_owner.get(f"/api/v1/organizations/{org}").status_code == 404
        scenario.login(owner, "owner")
        # The browser must propose and approve the policy itself. Host setup
        # establishes identity only, never the browser acquisition permission.
        initial = owner.get(source_path(scenario) + "/policies")
        assert initial.status_code == 200 and initial.json() == []
        cookies = [
            {
                "name": c.name,
                "value": c.value,
                "domain": "app.example.test",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Strict" if c.name.endswith("csrf") else "Lax",
            }
            for c in owner.cookies.jar
        ]
        token = str(owner.cookies["__Host-emailmonitor_session"])
    progress = Progress(runtime.publisher_database, token, SETTINGS)
    results = Results(progress.database, token, SETTINGS)
    cfg = config(scenario, Ledger(progress.database, token, SETTINGS), lease_seconds=120)
    publisher_config = PublisherConfig(
        environment="test", broker_url=cfg.broker_url, queue=cfg.queue
    )
    publication_counts = [0, 0]
    stop, release = threading.Event(), threading.Event()
    errors: list[str] = []
    requests: list[tuple[str, str]] = []
    policy_requests: list[tuple[str, dict[str, object]]] = []
    job_requests: list[dict[str, object]] = []
    review_requests: list[dict[str, Any]] = []

    def observe(request: RequestFrame) -> bool:
        requests.append((request.method, request.url.split("?")[0]))
        if request.method == "POST" and request.url == f"{ORIGIN}/api/v1/organizations/{org}/jobs":
            job_requests.append(json.loads(request.body))
        if (
            request.method == "POST"
            and request.url == f"{ORIGIN}/api/v1/organizations/{org}/reviews"
        ):
            review_requests.append(json.loads(request.body))
        if request.method == "POST" and request.url in (
            ORIGIN + source_path(scenario) + "/policies",
            ORIGIN + source_path(scenario) + "/policy-state",
        ):
            policy_requests.append((request.url.rsplit("/", 1)[-1], json.loads(request.body)))
        return False

    setup: dict[str, object] = {
        "kind": "bootstrap",
        "origin": ORIGIN,
        "journey": journey,
        "cookies": cookies,
        "assets": asset_manifest(ROOT / "apps/web/dist"),
        "initial_organization": str(org),
        "other_organization": str(other),
    }
    assert topology.browser_identifier is not None
    with browser_worker(
        cfg,
        topology.processes["gateway"],
        topology.browser_identifier,
        evidence=browser_evidence,
    ) as broker:

        def publisher() -> None:
            while not stop.wait(0.2):
                if release.is_set():
                    try:
                        published = publish_once(publisher_config, broker, progress, results, org)
                        publication_counts[0] += published.execution
                        publication_counts[1] += published.exports
                    except Exception as error:
                        errors.append(type(error).__name__)
                        stop.set()

        def control(action: str) -> None:
            if action == "publish":
                release.set()
            elif action == "wait_exports":
                wait_for(
                    lambda: (
                        bool(results.exports(org))
                        and all(e.state == "ready" for e in results.exports(org))
                    ),
                    seconds=8,
                )
            else:
                raise RuntimeError("Unexpected provider operator control")
            assert not errors

        def consumer_ready() -> bool:
            with broker.connection_for_read() as connection:
                channel = connection.channel()
                try:
                    return all(
                        channel.queue_declare(queue=q, passive=True).consumer_count > 0
                        for q in owned_queues(cfg.queue)
                    )
                finally:
                    channel.close()

        publisher_thread = threading.Thread(target=publisher, daemon=True)
        try:
            wait_for(consumer_ready, seconds=20)
            publisher_thread.start()
            evidence = run(app, setup, control, observe)
            assert not errors
        finally:
            stop.set()
            if publisher_thread.ident is not None:
                publisher_thread.join(timeout=10)
                assert not publisher_thread.is_alive()
    assert publication_counts[0] >= 1 and publication_counts[1] == 2
    print(
        json.dumps({"owned_publisher_passes_closed": True, "published_exports": 2}),
        flush=True,
    )
    # The pipe returns to the host only AFTER the real solo worker has joined.
    assert len(browser_evidence) == 1
    assert browser_evidence[0]["guest_stopped"] is True
    assert browser_evidence[0]["selected_peers"] == [[ENDPOINTS["fixture-a"][0], 443, HOST]] * 2
    receipts = snapshot(topology)
    calls = receipts["calls"]
    assert len(calls) == 2 and len(receipts["queries"]) == 4
    assert calls[1]["received_monotonic"] - calls[0]["received_monotonic"] >= 4.9
    assert all(
        c["method"] == "GET"
        and c["path"] == "/tooltip.html"
        and c["sni"] == HOST
        and set(c["headers"]) == {"Host", "Accept", "Connection"}
        for c in calls
    )
    assert len(job_requests) == 1
    expected_input = (
        {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        }
        if keyword
        else {"type": "url", "url": url}
    )
    assert job_requests[0]["input"] == expected_input
    options = job_requests[0]["options"]
    assert isinstance(options, dict) and options["allow_browser"] is True
    assert evidence["allow_browser"] is True
    assert evidence["journey"] == journey and evidence["keyboard"] is True
    assert evidence["network_errno"] == [101, 101] and evidence["interfaces"] == ["lo"]
    assert evidence["source_policy_review"] is True
    assert [kind for kind, _ in policy_requests] == ["policies", "policy-state"]
    assert policy_requests[0][1]["expected_version"] == 0
    requested_policy = policy_requests[0][1]["policy"]
    assert isinstance(requested_policy, dict)
    assert requested_policy["allowed_operations"] == [
        "search",
        "fetch_html",
        "extract_contacts",
        "retain_excerpt",
        "export_contacts",
        "browser",
    ]
    assert requested_policy["retention"] == {
        "raw_hours": 24,
        "excerpt_days": 30,
        "contact_days": 90,
    }
    assert requested_policy["allowed_hosts"] == ["synthetic.publisher.example"]
    assert requested_policy["execution_mode"] == "fixture"
    assert requested_policy["credential_reference"] is None
    assert requested_policy["permission_reference"] == "synthetic-fixtures-only"
    assert requested_policy["allowed_regions"] == ["test-only"]
    assert requested_policy["robots_handling"] == "fixture_no_network"
    assert requested_policy["purpose"] == "academic_contact_research"
    assert requested_policy["export_contacts_allowed"] is True
    assert requested_policy["limits"] == {
        "max_concurrent_requests": 1,
        "min_request_interval_seconds": 5,
        "max_articles_per_job": 500,
    }
    assert policy_requests[1][1] == {
        "expected_version": 1,
        "expected_revision": 1,
        "state": "approved",
    }
    with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
        approved_policy = c.execute(
            text(
                "SELECT version,row_version,state,policy,created_by,reviewed_by "
                "FROM emailmonitor.source_policies WHERE organization_id=:org "
                "AND source_id='synthetic-publisher'"
            ),
            {"org": org},
        ).one()
        assert (
            approved_policy.version,
            approved_policy.row_version,
            approved_policy.state,
        ) == (
            1,
            2,
            "approved",
        )
        assert (
            approved_policy.created_by
            == approved_policy.reviewed_by
            == scenario.identities["owner"]
        )
        # SQL stores the validated policy, including the same explicit permissions.
        assert (
            approved_policy.policy["allowed_operations"] == requested_policy["allowed_operations"]
        )
        assert approved_policy.policy["retention"] == requested_policy["retention"]
        policy_audit = c.execute(
            text(
                "SELECT action,actor_id FROM emailmonitor.audit_events "
                "WHERE organization_id=:org AND action IN "
                "('source.policy.proposed','source.policy.approved')"
            ),
            {"org": org},
        ).all()
        assert {row.action for row in policy_audit} == {
            "source.policy.proposed",
            "source.policy.approved",
        }
        assert len(policy_audit) == 2
        assert all(row.actor_id == scenario.identities["owner"] for row in policy_audit)
        rows = c.execute(
            text(
                "SELECT id,state,request FROM emailmonitor.jobs "
                "WHERE organization_id=:org AND kind='extraction'"
            ),
            {"org": org},
        ).all()
        assert len(rows) == 1 and rows[0].state == "completed"
        job = UUID(str(rows[0].id))
        _assert_stored_operator_request(rows[0].request, job_requests[0])
        discovery = c.execute(
            text(
                "SELECT plan,checkpoint FROM emailmonitor.discovery "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": job},
        ).one()
        if keyword:
            _assert_keyword_checkpoint(discovery.plan, discovery.checkpoint)
        else:
            assert discovery.plan["classification"] == "article"
            assert discovery.checkpoint["pages"] == []
            assert discovery.checkpoint["articles"] == [url]
            assert discovery.checkpoint["next_url"] is None
            assert discovery.checkpoint["discovery_complete"] is True
            assert discovery.checkpoint["completeness"] == "single_article"
            assert discovery.checkpoint["reason"] == "single_article"
        items = c.execute(
            text(
                "SELECT work_kind,input_url FROM emailmonitor.execution_items "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": job},
        ).all()
        if keyword:
            assert {item.input_url for item in items if item.work_kind == "article"} == set(
                discovery.checkpoint["articles"]
            )
            assert len([item for item in items if item.work_kind == "article"]) == 4
            assert len([item for item in items if item.work_kind == "discover"]) == 2
        else:
            assert [(item.work_kind, item.input_url) for item in items] == [("article", url)]
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects e "
                    "JOIN emailmonitor.execution_items i ON "
                    "(i.organization_id,i.job_id,i.id)=(e.organization_id,e.job_id,e.item_id) "
                    "WHERE e.organization_id=:org AND e.job_id=:job AND i.work_kind='article'"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == expected_articles
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.association_reviews "
                    "WHERE organization_id=:org"
                ),
                {"org": org},
            ).scalar_one()
            == expected_articles
        )
        tickets = c.execute(
            text(
                "SELECT operation,state FROM emailmonitor.source_resource_requests "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": job},
        ).all()
        assert len(tickets) == expected_tickets and all(t.state == "finished" for t in tickets)
        assert {t.operation for t in tickets} == {"browser"}
        usage: dict[str, Any] = c.execute(
            text("SELECT emailmonitor.administration_usage(:org)"), {"org": org}
        ).scalar_one()
        assert usage["source_resource_attempts"] == expected_tickets
        assert usage["active_units"].get("http", 0) == 0
        assert usage["active_units"].get("browser", 0) == 0
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_outbox "
                    "WHERE organization_id=:org AND job_id=:job AND published_at IS NOT NULL"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            >= 1
        )
    retained = [
        ArticleObservation.model_validate(r["observation"])
        for r in progress.extraction.read(org, job)
    ]
    assert len(retained) == expected_articles
    if keyword:
        _assert_keyword_results(progress, results, org, job, retained)
    retained = [row for row in retained if row.url == url]
    assert len(retained) == 1
    assert retained[0].route == "browser_dom" and retained[0].status == "observed"
    assert retained[0].url == url
    assert any(author.display_name == "Elena Park" for author in retained[0].authors)
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == expected_articles
    assert {contact.raw_address for contact in contacts} == expected_addresses
    assert {contact.source_url for contact in contacts} == (
        {
            "https://synthetic.publisher.example/" + name
            for name in ("article-a.html", "article-b.html", "tooltip.html")
        }
        if keyword
        else {url}
    )
    assert len(review_requests) == expected_articles
    assert {row["association_id"] for row in review_requests} == {
        str(contact.association_id) for contact in contacts
    }
    exports = results.exports(org)
    assert len(exports) == 2 and {e.format for e in exports} == {"csv", "xlsx"}
    digests = []
    for export in exports:
        artifact = results.download(org, export.id)
        with ZipFile(io.BytesIO(artifact.body)) as archive:
            joined = b"\n".join(archive.read(name) for name in archive.namelist())
            assert all(address.encode() in joined for address in expected_addresses)
            assert all(contact.source_url.encode() in joined for contact in contacts)
        if keyword:
            assert export.contacts == 4 and export.article_outcomes == 4
            _assert_exact_export(artifact.body, export.format, contacts)
        digests.append(hashlib.sha256(artifact.body).hexdigest())
    base = f"{ORIGIN}/api/v1/organizations/{org}"
    for suffix in (
        "/jobs",
        f"/jobs/{job}/plan",
        f"/jobs/{job}/start",
        "/reviews",
        "/exports",
    ):
        assert ("POST", base + suffix) in requests
    assert {
        path for method, path in requests if method == "GET" and path.endswith("/download")
    } == {base + f"/exports/{export.id}/download" for export in exports}
    with APIClient(runtime.app, ORIGIN) as client:
        scenario.login(client, "owner_b")
        assert client.get(f"/api/v1/organizations/{org}/jobs/{job}").status_code == 404
        for export in exports:
            assert (
                client.get(f"/api/v1/organizations/{org}/exports/{export.id}/download").status_code
                == 404
            )
    if keyword:
        _assert_keyword_tenant_denials(runtime, scenario, progress, results, job, contacts, exports)
    print(
        json.dumps(
            {
                "proof": (
                    "NORMAL_OPERATOR_KEYWORD_BROWSER_ISOLATED_REVIEW_EXPORT"
                    if keyword
                    else "NORMAL_OPERATOR_TOOLTIP_BROWSER_ISOLATED_REVIEW_EXPORT"
                ),
                "articles": expected_articles,
                "source_tickets": expected_tickets,
                "policy_approved_through_keyboard": True,
                "browser_opt_in": True,
                "guest_stopped": True,
                "actual_dns_selected_peers": browser_evidence[0]["selected_peers"],
                "formats": ["csv", "xlsx"],
                "artifact_digests": digests,
                "tenant_b": "denied",
                "browser_network": "none",
            }
        ),
        flush=True,
    )


def _assert_keyword_checkpoint(plan: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    origin = "https://synthetic.publisher.example/"
    assert plan["classification"] == "search_results"
    assert plan["original_query"] == plan["effective_query"] == "Myocardial Infarction"
    assert checkpoint == {
        "schema_version": "1.0",
        "status": "completed",
        "reason": "pagination_exhausted",
        "next_url": None,
        "pages": [origin + f"search-page-{n}.html" for n in (1, 2)],
        "digests": [
            hashlib.sha256((ROOT / f"fixtures/html/search-page-{n}.html").read_bytes()).hexdigest()
            for n in (1, 2)
        ],
        "articles": [
            origin + name
            for name in ("article-a.html", "article-b.html", "tooltip.html", "no-contact.html")
        ],
        "raw_entries": 5,
        "duplicates": 1,
        "reported_total": 5,
        "completeness": "pagination_exhausted",
        "api_fallback": "unavailable_not_attempted",
        "discovery_complete": True,
        "extraction_implemented": False,
    }


def _assert_keyword_results(
    progress: Progress,
    results: Results,
    org: UUID,
    job: UUID,
    retained: list[ArticleObservation],
) -> None:
    final = progress.snapshot(org, job)
    assert final.state == "completed" and final.progress_percent == 100
    assert final.discovery_pages == 2 and final.source_reported_total == 5
    assert final.unique_articles == 4 and final.duplicates == 1
    assert final.discovery_complete and final.completeness == "pagination_exhausted"
    assert final.discovery_stop_reason == "pagination_exhausted"
    assert final.counts.model_dump() == {
        "discovered": 4,
        "pending": 0,
        "active": 0,
        "retry_wait": 0,
        "terminal": 4,
        "by_outcome": {"succeeded": 3, "no_contact": 1},
    }
    assert final.accepted_associations == 4 and final.review_needed_associations == 0
    by_name = {row.url.rsplit("/", 1)[-1]: row for row in retained}
    for name in ("article-a.html", "article-b.html", "no-contact.html"):
        observation = by_name[name]
        digest = hashlib.sha256((ROOT / "fixtures/html" / name).read_bytes()).hexdigest()
        assert observation.route == "html"
        assert observation.content_digest == observation.acquisition_digest == digest
    first = by_name["article-a.html"].authors[0]
    assert first.display_name == "Mira Rao" and first.first
    no_contact = by_name["no-contact.html"]
    assert no_contact.status == "no_contact" and no_contact.candidates == []
    assert no_contact.authors[0].display_name == "Leena Shah"
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert {(row.author_name, row.raw_address) for row in contacts} == {
        ("Alex Chen", "alex.chen@example.org"),
        ("Ravi Das", "ravi.das@example.org"),
        ("Noor Ibrahim", "noor.ibrahim@example.org"),
        ("Elena Park", "elena.park@example.org"),
    }
    assert not next(row for row in contacts if row.author_name == "Alex Chen").first_author
    assert all(
        row.state == "accepted" and row.association_reason == "reviewed_evidence"
        for row in contacts
    )
    assert all(
        candidate.raw_address != "support@example.org"
        for row in retained
        for candidate in row.candidates
    )
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        reviews = c.execute(
            text(
                "SELECT r.association_id,r.reason,r.action,r.expected_revision,r.new_record,"
                "array_agg(e.evidence_id) AS evidence_ids FROM emailmonitor.association_reviews r "
                "JOIN emailmonitor.association_review_evidence e ON "
                "(e.organization_id,e.batch_id,e.review_id)=(r.organization_id,r.batch_id,r.id) "
                "WHERE r.organization_id=:org GROUP BY r.organization_id,r.batch_id,r.id"
            ),
            {"org": org},
        ).all()
        assert len(reviews) == 4
        for contact in contacts:
            review = next(row for row in reviews if row.association_id == contact.association_id)
            assert review.reason == "Inspected combined keyword citation for " + contact.raw_address
            assert review.action == "accept" and review.expected_revision == contact.revision - 1
            assert set(review.evidence_ids) == set(contact.evidence_ids)
        assert len({row.reason for row in reviews}) == 4


def _assert_exact_export(body: bytes, format: str, contacts: tuple[Contact, ...]) -> None:
    with ZipFile(io.BytesIO(body)) as archive:
        if format == "csv":
            rows = list(csv.reader(io.StringIO(archive.read("contacts.csv").decode())))
        else:
            namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            rows = [
                [
                    cell.findtext("s:is/s:t", default="", namespaces=namespace)
                    for cell in row.findall("s:c", namespace)
                ]
                for row in sheet.findall("s:sheetData/s:row", namespace)
            ]
    assert len(rows) == 5
    values = [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]
    assert {row["Association ID"] for row in values} == {str(c.association_id) for c in contacts}
    assert {row["Observed address"] for row in values} == {c.raw_address for c in contacts}
    assert {(row["Association ID"], row["Observed address"], row["Author"]) for row in values} == {
        (str(c.association_id), c.raw_address, c.author_name) for c in contacts
    }
    assert all(row["Association state"] == "accepted" for row in values)
    assert all(row["Author"] not in {"Mira Rao", "Leena Shah"} for row in values)


def _assert_keyword_tenant_denials(
    runtime: RuntimeBundle,
    scenario: Scenario,
    progress: Progress,
    results: Results,
    job: UUID,
    contacts: tuple[Contact, ...],
    exports: tuple[ExportState, ...],
) -> None:
    org, other = scenario.organizations
    cursor = f"{org}/{job}:{progress.snapshot(org, job).last_sequence}"
    contact_cursor = results.contacts(org, Filters(job_id=job), limit=1).next_cursor
    assert contact_cursor
    batches = progress.associations.batches(org, job)
    assert len(batches) == 4
    with APIClient(runtime.app, ORIGIN) as client:
        csrf = scenario.login(client, "owner_b")
        assert client.get(f"/api/v1/organizations/{other}").status_code == 200
        assert client.get(f"/api/v1/organizations/{org}").status_code == 404
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        for context in (org, other):
            base = f"/api/v1/organizations/{context}"
            for suffix in (
                f"/jobs/{job}",
                f"/jobs/{job}/progress",
                f"/jobs/{job}/progress/items",
                f"/jobs/{job}/associations",
            ):
                assert client.get(base + suffix).status_code == 404
            for batch in batches:
                for suffix in (
                    f"/association-batches/{batch['id']}",
                    f"/association-batches/{batch['id']}/reviews",
                ):
                    assert client.get(base + suffix).status_code == 404
            for suffix in ("/contacts", "/article-outcomes"):
                assert client.get(base + suffix, params={"job_id": str(job)}).status_code == 404
            for contact in contacts:
                for suffix in (
                    f"/contacts/{contact.association_id}?batch_id={contact.batch_id}",
                    f"/association-batches/{contact.batch_id}",
                    f"/association-batches/{contact.batch_id}/reviews",
                    *(f"/evidence/{e}?batch_id={contact.batch_id}" for e in contact.evidence_ids),
                ):
                    assert client.get(base + suffix).status_code == 404
                assert (
                    client.post(
                        base + "/reviews",
                        headers=headers,
                        json={
                            "batch_id": str(contact.batch_id),
                            "association_id": str(contact.association_id),
                            "expected_revision": contact.revision,
                            "action": "accept",
                            "author_id": str(contact.author_id),
                            "evidence_ids": [str(e) for e in contact.evidence_ids],
                            "reason": "Cross-tenant mutation must be refused",
                        },
                    ).status_code
                    == 404
                )
            for export in exports:
                assert (
                    client.post(
                        base + f"/exports/{export.id}/revoke",
                        headers=headers,
                        json={"expected_revision": export.revision},
                    ).status_code
                    == 404
                )
                for suffix in (f"/exports/{export.id}", f"/exports/{export.id}/download"):
                    assert client.get(base + suffix).status_code == 404
            response = client.get(
                base + "/contacts", params={"job_id": str(job), "cursor": contact_cursor}
            )
            assert response.status_code == (404 if context == org else 422)

            async def bounded_events(base: str = base, context: UUID = context) -> None:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=runtime.app),
                    base_url=ORIGIN,
                    cookies=client.cookies,
                ) as stream:
                    for replay in (None, cursor):
                        response = await asyncio.wait_for(
                            stream.get(
                                base + f"/jobs/{job}/events",
                                headers={} if replay is None else {"Last-Event-ID": replay},
                            ),
                            timeout=5,
                        )
                        expected = 409 if context == other and replay is not None else 404
                        assert response.status_code == expected
                        assert "text/event-stream" not in response.headers.get("content-type", "")

            asyncio.run(bounded_events())
    assert all(results.state(org, export.id).state == "ready" for export in exports)
    # The denied, valid mutation bodies leave all four saved reviews unchanged.
    assert all(
        row.revision == next(c.revision for c in contacts if c.association_id == row.association_id)
        for row in results.contacts(org, Filters(job_id=job)).items
    )


def _assert_stored_operator_request(
    stored: dict[str, Any],
    submitted: dict[str, object],
) -> None:
    # The UI request assertion above checks the exact submitted fields. Persistence
    # uses the validated model, retaining defaults and omitting only None fields.
    assert stored == JobRequest.model_validate(submitted).model_dump(mode="json", exclude_none=True)
