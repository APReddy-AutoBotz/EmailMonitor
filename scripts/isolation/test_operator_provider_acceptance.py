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
from emailmonitor.progress.broker import publish as publish_execution
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import publish as publish_exports
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from emailmonitor.runtime.assembly import RuntimeBundle, owned_test_runtime
from emailmonitor.runtime.assembly import TestRuntimeConfig as RuntimeConfig
from operator_provider_worker import provider_worker
from operator_ui_protocol import RequestFrame, asset_manifest
from run_operator_ui_acceptance import run
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import config, wait_for
from test_source_foundation import policy_body, source_path
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
        _provider_operator_journey(topology, scenario, monkeypatch, runtime)
    with APIClient(runtime.app, ORIGIN) as closed:
        assert closed.get("/healthz").status_code == 503
    print(
        json.dumps({"owned_test_runtime_closed": True, "separate_api_publisher_pools": True}),
        flush=True,
    )


def _provider_operator_journey(
    topology: Topology, scenario: Scenario, monkeypatch: pytest.MonkeyPatch, runtime: RuntimeBundle
) -> None:
    from emailmonitor.parsing import xml_channel

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
        csrf = scenario.login(owner, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        # Explicit reviewed synthetic precondition through the existing governance API.
        # Never alter the UI's HTML default, a historical policy, or live permissions.
        policy = policy_body(
            allowed_operations=[
                "search",
                "fetch_xml",
                "extract_contacts",
                "retain_excerpt",
                "export_contacts",
            ],
            retention={"raw_hours": 0, "excerpt_days": 30, "contact_days": 90},
        )
        response = owner.post(
            source_path(scenario) + "/policies",
            headers=headers,
            json={"expected_version": 0, "policy": policy},
        )
        assert response.status_code == 201, response.text
        assert (
            owner.post(
                source_path(scenario) + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
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
    stop, release = threading.Event(), threading.Event()
    errors: list[str] = []
    requests: list[tuple[str, str]] = []

    def observe(request: RequestFrame) -> bool:
        requests.append((request.method, request.url.split("?")[0]))
        return False

    setup: dict[str, object] = {
        "kind": "bootstrap",
        "origin": ORIGIN,
        "journey": "controlled_provider",
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
                        publish_execution(broker, progress, org)
                        publish_exports(broker, results, org)
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
    # The pipe returns to the host only AFTER the real solo worker has joined.
    assert len(profiles) == 2
    calls = snapshot(topology)["calls"]
    assert len(calls) == 3 and calls[0]["method"] == "PUT"
    assert all(c["method"] == "GET" and c["path"].endswith("?view=FULL") for c in calls[1:])
    assert evidence["journey"] == "controlled_provider" and evidence["keyboard"] is True
    assert evidence["network_errno"] == [101, 101] and evidence["interfaces"] == ["lo"]
    with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
        rows = c.execute(
            text(
                "SELECT id,state FROM emailmonitor.jobs "
                "WHERE organization_id=:org AND kind='extraction'"
            ),
            {"org": org},
        ).all()
        assert len(rows) == 1 and rows[0].state == "completed"
        job = UUID(str(rows[0].id))
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 2
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.association_reviews "
                    "WHERE organization_id=:org"
                ),
                {"org": org},
            ).scalar_one()
            == 2
        )
        tickets = c.execute(
            text(
                "SELECT operation,state FROM emailmonitor.source_resource_requests "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": job},
        ).all()
        assert len(tickets) == 3 and all(t.state == "finished" for t in tickets)
        assert {t.operation for t in tickets} == {"search", "fetch_xml"}
        usage: dict[str, Any] = c.execute(
            text("SELECT emailmonitor.administration_usage(:org)"), {"org": org}
        ).scalar_one()
        assert usage["source_resource_attempts"] == 3
        assert usage["active_units"].get("http", 0) == 0
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_outbox "
                    "WHERE organization_id=:org AND job_id=:job AND published_at IS NOT NULL"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            >= 3
        )
    retained = [
        RetainedXml.model_validate_json(json.dumps(r["observation"]))
        for r in progress.extraction.read(org, job)
    ]
    assert len(retained) == 2 and {r.requested_identifier.kind for r in retained} == {"doi", "pii"}
    assert all(r.provider is not None and r.provider.requested_view == "FULL" for r in retained)
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == 2
    exports = results.exports(org)
    assert len(exports) == 2 and {e.format for e in exports} == {"csv", "xlsx"}
    digests = []
    for export in exports:
        artifact = results.download(org, export.id)
        with ZipFile(io.BytesIO(artifact.body)) as archive:
            joined = b"\n".join(archive.read(name) for name in archive.namelist())
            assert b"Second@example.org" in joined and b"beta@example.org" in joined
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
                "proof": "NORMAL_OPERATOR_RABBITMQ_PROVIDER_ISOLATED_REVIEW_EXPORT",
                "articles": 2,
                "source_tickets": 3,
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
