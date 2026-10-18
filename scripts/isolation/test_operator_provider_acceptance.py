"""Normal authenticated UI and registered RabbitMQ task, not manual journey execution."""

import hashlib
import io
import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID
from zipfile import ZipFile

import pytest
from api_client import APIClient
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from emailmonitor.runtime.assembly import RuntimeBundle, owned_test_runtime
from emailmonitor.runtime.assembly import TestRuntimeConfig as RuntimeConfig
from emailmonitor.runtime.publisher import TestPublisherConfig as PublisherConfig
from emailmonitor.runtime.publisher import publish_once
from emailmonitor.sources import provider_documents as catalog
from operator_provider_worker import provider_worker
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
from transport_topology import Topology
from xml_image_evidence import require_packaged_image

ROOT = Path(__file__).resolve().parents[2]


def test_actual_provider_operator_ui(
    topology: Topology, scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_provider_operator_ui(topology, scenario, monkeypatch)


def test_actual_provider_direct_article_url_operator_ui(
    topology: Topology, scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_provider_operator_ui(topology, scenario, monkeypatch, direct_url=True)


def _run_provider_operator_ui(
    topology: Topology,
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    *,
    direct_url: bool = False,
) -> None:
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
        _provider_operator_journey(topology, scenario, monkeypatch, runtime, direct_url=direct_url)
    with APIClient(runtime.app, ORIGIN) as closed:
        assert closed.get("/healthz").status_code == 503
    print(
        json.dumps({"owned_test_runtime_closed": True, "separate_api_publisher_pools": True}),
        flush=True,
    )


def _provider_operator_journey(
    topology: Topology,
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    runtime: RuntimeBundle,
    *,
    direct_url: bool = False,
) -> None:
    from emailmonitor.parsing import xml_channel

    assert type(direct_url) is bool
    expected_articles = 1 if direct_url else 2
    expected_tickets = 1 if direct_url else 3
    expected_addresses = (
        {"Second@example.org"} if direct_url else {"Second@example.org", "beta@example.org"}
    )
    configure(topology)
    profiles: list[Mapping[str, object]] = []
    verify = xml_channel.verify_profile

    def verified(metadata: Mapping[str, object]) -> None:
        verify(metadata)
        require_packaged_image(metadata)
        profiles.append(metadata)

    monkeypatch.setattr(xml_channel, "verify_profile", verified)
    app = runtime.app
    org, other = scenario.organizations
    with APIClient(app, ORIGIN) as owner, scenario.client() as other_owner:
        csrf = scenario.login(other_owner, "owner_b")
        assert (
            other_owner.post(
                f"/api/v1/organizations/{other}/members",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"identity_id": str(scenario.identities["owner"]), "role": "viewer"},
            ).status_code
            == 201
        )
        assert other_owner.get(f"/api/v1/organizations/{org}").status_code == 404
        scenario.login(owner, "owner")
        # The browser must propose and approve the policy itself. Host setup
        # establishes identity only, never the XML acquisition permission.
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

    def observe(request: RequestFrame) -> bool:
        requests.append((request.method, request.url.split("?")[0]))
        if request.method == "POST" and request.url == f"{ORIGIN}/api/v1/organizations/{org}/jobs":
            job_requests.append(json.loads(request.body))
        if request.method == "POST" and request.url in (
            ORIGIN + source_path(scenario) + "/policies",
            ORIGIN + source_path(scenario) + "/policy-state",
        ):
            policy_requests.append((request.url.rsplit("/", 1)[-1], json.loads(request.body)))
        return False

    setup: dict[str, object] = {
        "kind": "bootstrap",
        "origin": ORIGIN,
        "journey": "controlled_provider",
        "direct_article_url": direct_url,
        "cookies": cookies,
        "assets": asset_manifest(ROOT / "apps/web/dist"),
        "initial_organization": str(org),
        "other_organization": str(other),
    }
    with provider_worker(cfg, topology.processes["gateway"]) as broker:

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
    assert publication_counts[0] >= expected_tickets and publication_counts[1] == 2
    print(
        json.dumps({"owned_publisher_passes_closed": True, "published_exports": 2}),
        flush=True,
    )
    # The pipe returns to the host only AFTER the real solo worker has joined.
    assert len(profiles) == expected_articles
    calls = snapshot(topology)["calls"]
    if direct_url:
        assert len(calls) == 1
        assert calls[0]["method"] == "GET"
        assert calls[0]["path"] == "/content/article/doi/10.9999/synthetic.1?view=FULL"
    else:
        assert len(calls) == 3 and calls[0]["method"] == "PUT"
        assert all(c["method"] == "GET" and c["path"].endswith("?view=FULL") for c in calls[1:])
    assert evidence["direct_article_url"] is direct_url
    assert len(job_requests) == 1
    expected_input = (
        {"type": "url", "url": catalog.DOI_URL}
        if direct_url
        else {"type": "keyword", "source_id": catalog.SOURCE, "original_query": catalog.QUERY}
    )
    assert job_requests[0]["input"] == expected_input
    assert evidence["journey"] == "controlled_provider" and evidence["keyboard"] is True
    assert evidence["network_errno"] == [101, 101] and evidence["interfaces"] == ["lo"]
    assert evidence["source_policy_review"] is True
    assert [kind for kind, _ in policy_requests] == ["policies", "policy-state"]
    assert policy_requests[0][1]["expected_version"] == 0
    requested_policy = policy_requests[0][1]["policy"]
    assert isinstance(requested_policy, dict)
    assert requested_policy["allowed_operations"] == [
        "search",
        "fetch_xml",
        "extract_contacts",
        "retain_excerpt",
        "export_contacts",
    ]
    assert requested_policy["retention"] == {"raw_hours": 0, "excerpt_days": 30, "contact_days": 90}
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
        assert (approved_policy.version, approved_policy.row_version, approved_policy.state) == (
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
        if direct_url:
            assert rows[0].request["input"] == expected_input
            discovery = c.execute(
                text(
                    "SELECT plan,checkpoint FROM emailmonitor.discovery "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).one()
            assert discovery.plan["classification"] == "article"
            assert discovery.checkpoint["pages"] == []
            assert discovery.checkpoint["articles"] == [catalog.DOI_URL]
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
            assert [(item.work_kind, item.input_url) for item in items] == [
                ("article", catalog.DOI_URL)
            ]
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects "
                    "WHERE organization_id=:org AND job_id=:job"
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
        assert {t.operation for t in tickets} == (
            {"fetch_xml"} if direct_url else {"search", "fetch_xml"}
        )
        usage: dict[str, Any] = c.execute(
            text("SELECT emailmonitor.administration_usage(:org)"), {"org": org}
        ).scalar_one()
        assert usage["source_resource_attempts"] == expected_tickets
        assert usage["active_units"].get("http", 0) == 0
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_outbox "
                    "WHERE organization_id=:org AND job_id=:job AND published_at IS NOT NULL"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            >= expected_tickets
        )
    retained = [
        RetainedXml.model_validate_json(json.dumps(r["observation"]))
        for r in progress.extraction.read(org, job)
    ]
    assert len(retained) == expected_articles
    assert {r.requested_identifier.kind for r in retained} == (
        {"doi"} if direct_url else {"doi", "pii"}
    )
    if direct_url:
        assert retained[0].url == catalog.DOI_URL
        assert (
            retained[0].canonical_url
            == "https://api.elsevier.com/content/article/doi/10.9999/synthetic.1"
        )
        assert retained[0].requested_identifier.value == "10.9999/synthetic.1"
    assert all(r.provider is not None and r.provider.requested_view == "FULL" for r in retained)
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == expected_articles
    assert {contact.raw_address for contact in contacts} == expected_addresses
    if direct_url:
        assert {contact.source_url for contact in contacts} == {catalog.DOI_URL}
    exports = results.exports(org)
    assert len(exports) == 2 and {e.format for e in exports} == {"csv", "xlsx"}
    digests = []
    for export in exports:
        artifact = results.download(org, export.id)
        with ZipFile(io.BytesIO(artifact.body)) as archive:
            joined = b"\n".join(archive.read(name) for name in archive.namelist())
            assert all(address.encode() in joined for address in expected_addresses)
            if direct_url:
                assert b"beta@example.org" not in joined
                assert catalog.PII_URL.encode() not in joined
                assert catalog.SEARCH_URL.encode() not in joined
            assert all(contact.source_url.encode() in joined for contact in contacts)
        digests.append(hashlib.sha256(artifact.body).hexdigest())
    base = f"{ORIGIN}/api/v1/organizations/{org}"
    for suffix in ("/jobs", f"/jobs/{job}/plan", f"/jobs/{job}/start", "/reviews", "/exports"):
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
    print(
        json.dumps(
            {
                "proof": "NORMAL_OPERATOR_DIRECT_XML_URL_ISOLATED_REVIEW_EXPORT"
                if direct_url
                else "NORMAL_OPERATOR_RABBITMQ_PROVIDER_ISOLATED_REVIEW_EXPORT",
                "articles": expected_articles,
                "source_tickets": expected_tickets,
                "direct_article_url": direct_url,
                "policy_approved_through_keyboard": True,
                "parser_image_ids": sorted({str(p["Image"]) for p in profiles}),
                "actual_parser_profiles": len(profiles),
                "formats": ["csv", "xlsx"],
                "artifact_digests": digests,
                "tenant_b": "denied",
                "browser_network": "none",
            }
        ),
        flush=True,
    )
