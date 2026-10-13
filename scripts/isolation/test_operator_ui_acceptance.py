"""Required disposable CI: actual React → ASGI → PostgreSQL/outbox → broker/worker."""

import hashlib
import io
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.broker import publish as publish_execution
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import publish as publish_exports
from emailmonitor.results.service import Results
from operator_ui_protocol import RequestFrame, asset_manifest
from run_operator_ui_acceptance import run
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import config, wait_for, worker
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

ROOT = Path(__file__).resolve().parents[2]


def test_required_actual_keyboard_operator_ui(scenario: Scenario, tmp_path: Path) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true"
    ):
        raise RuntimeError("Required reviewed disposable UI CI only")
    # Existing provider assembly requires explicit test identity, never production activation.
    app = create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation)
    org, other = scenario.organizations
    with APIClient(app, ORIGIN) as owner, scenario.client() as other_owner:
        other_nonce = scenario.login(other_owner, "owner_b")
        response = other_owner.post(
            f"/api/v1/organizations/{other}/members",
            headers={"Origin": ORIGIN, "X-CSRF-Token": other_nonce},
            json={"identity_id": str(scenario.identities["owner"]), "role": "viewer"},
        )
        assert response.status_code == 201, response.text
        assert other_owner.get(f"/api/v1/organizations/{org}").status_code == 404
        scenario.login(owner, "owner")
        session = owner.get("/api/v1/auth/session", headers={"X-EmailMonitor-UI": "session"})
        assert session.status_code == 200
        order = [row["organization_id"] for row in session.json()["memberships"]]
        # UI selects first membership. Do not assume random UUID ordering.
        assert len(order) == 2
        cookies = [
            {
                "name": value.name,
                "value": value.value,
                "domain": "app.example.test",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Strict" if value.name.endswith("csrf") else "Lax",
            }
            for value in owner.cookies.jar
        ]
        token = next(
            value.value
            for value in owner.cookies.jar
            if value.name == "__Host-emailmonitor_session"
        )
    assert token is not None
    progress = Progress(scenario.foundation.database, token, SETTINGS)
    results = Results(progress.database, token, SETTINGS)
    cfg = config(scenario, Ledger(progress.database, token, SETTINGS))
    broker, _ = create_worker(cfg)
    stop, release = threading.Event(), threading.Event()
    errors: list[str] = []
    held, hold_contacts, fault_contacts = threading.Event(), threading.Event(), threading.Event()
    held.set()
    observed_hold = threading.Event()
    hold_events = threading.Event()
    late_events: list[int] = []
    late_replies: list[int] = []
    faults: list[int] = []

    def before_reply(request: RequestFrame) -> bool:
        if request.method == "GET" and request.url.startswith(
            f"{ORIGIN}/api/v1/organizations/{org}/contacts?"
        ):
            if fault_contacts.is_set():
                fault_contacts.clear()
                faults.append(request.identifier)
                return True
            if hold_contacts.is_set():
                observed_hold.set()
                if not held.wait(timeout=8):
                    raise RuntimeError("Owned late-response release deadline exceeded")
                late_replies.append(request.identifier)
        if request.method == "GET" and request.url.endswith("/events") and hold_events.is_set():
            observed_hold.set()
            if not held.wait(timeout=8):
                raise RuntimeError("Owned old-event release deadline exceeded")
            late_events.append(request.identifier)
        return False

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
        elif action == "fault_contacts":
            fault_contacts.set()
        elif action == "hold_events":
            held.clear()
            observed_hold.clear()
            hold_events.set()
        elif action == "hold_contacts":
            held.clear()
            observed_hold.clear()
            hold_contacts.set()
        elif action == "wait_held":
            if not observed_hold.wait(timeout=5):
                raise RuntimeError("Actual old-tenant response was not held")
        elif action == "release_contacts":
            held.set()
            hold_contacts.clear()
            hold_events.clear()
        elif action == "wait_jobs":

            def complete() -> bool:
                with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
                    rows: Sequence[object] = (
                        c.execute(
                            text(
                                "SELECT state FROM emailmonitor.jobs "
                                "WHERE organization_id=:org AND kind='extraction'"
                            ),
                            {"org": org},
                        )
                        .scalars()
                        .all()
                    )
                return bool(rows) and all(
                    value in {"completed", "completed_partial", "failed", "cancelled"}
                    for value in rows
                )

            wait_for(complete, seconds=8)
        elif action == "wait_exports":
            wait_for(
                lambda: (
                    bool(results.exports(org))
                    and all(value.state == "ready" for value in results.exports(org))
                ),
                seconds=8,
            )
        else:
            raise RuntimeError("Unexpected fixed diagnostic control")
        if errors:
            raise RuntimeError("Actual outbox publisher failed")

    assets = asset_manifest(ROOT / "apps/web/dist")
    assert "index.html" in assets
    setup: dict[str, object] = {
        "kind": "bootstrap",
        "origin": ORIGIN,
        "cookies": cookies,
        "assets": assets,
        "other_organization": str(other),
        "initial_organization": str(org),
    }
    thread = threading.Thread(target=publisher, daemon=True)
    try:
        with worker(cfg, tmp_path):

            def consumer_ready() -> bool:
                with broker.connection_for_read() as connection:
                    channel = connection.channel()
                    try:
                        return bool(
                            channel.queue_declare(queue=cfg.queue, passive=True).consumer_count > 0
                        )
                    except Exception:
                        return False
                    finally:
                        channel.close()

            wait_for(consumer_ready)
            thread.start()
            evidence = run(app, setup, control, before_reply)
            assert len(faults) == 1 and len(late_replies) >= 1 and len(late_events) >= 1
            assert not errors
            assert all(
                evidence[name] is True
                for name in [
                    "keyboard",
                    "keyword_partial",
                    "url_no_contact",
                    "review",
                    "pause_resume_cancel_dismiss",
                    "dialog_focus_restore",
                    "optional_field_preview",
                    "usage_audit_settings",
                    "download_cancelled",
                    "org_switch",
                    "readonly_role",
                ]
            )
            assert evidence["network_errno"] == [101, 101] and evidence["interfaces"] == ["lo"]
            with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
                jobs = c.execute(
                    text(
                        "SELECT id,state FROM emailmonitor.jobs "
                        "WHERE organization_id=:org AND kind='extraction' ORDER BY created_at"
                    ),
                    {"org": org},
                ).all()
                reviews: int = c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.association_reviews "
                        "WHERE organization_id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
                effects: int = c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_effects "
                        "WHERE organization_id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
            assert (
                len(jobs) == 2
                and jobs[0].state == "completed_partial"
                and jobs[1].state == "completed"
            )
            with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
                event_types: Sequence[str] = (
                    c.execute(
                        text(
                            "SELECT event_type FROM emailmonitor.execution_events "
                            "WHERE organization_id=:org AND job_id=:job ORDER BY sequence"
                        ),
                        {"org": org, "job": jobs[0].id},
                    )
                    .scalars()
                    .all()
                )
            assert "job.paused" in event_types and event_types.count("job.queued") >= 2
            assert "job.cancelled" not in event_types
            first = progress.snapshot(org, UUID(str(jobs[0].id)))
            assert first.counts.discovered == first.counts.terminal == 4
            assert (
                first.counts.by_outcome["unsupported"] == first.counts.by_outcome["no_contact"] == 1
            )
            assert reviews == 1 and effects >= 5
            exports = results.exports(org)
            assert len(exports) == 1 and exports[0].state == "ready"
            artifact = results.download(org, exports[0].id)
            assert artifact.body.startswith(b"PK") and len(artifact.body) > 1000
            with ZipFile(io.BytesIO(artifact.body)) as archive:
                contact_sheet = archive.read("xl/worksheets/sheet1.xml")
            assert b">Affiliations<" not in contact_sheet and b">Article title<" in contact_sheet

            print(
                json.dumps(
                    {
                        **evidence,
                        "actual_postgresql": True,
                        "actual_broker_worker": True,
                        "review_receipts": reviews,
                        "durable_effects": effects,
                        "export_sha256": hashlib.sha256(artifact.body).hexdigest(),
                        "export_bytes": len(artifact.body),
                        "sse_transport": "actual_frames_bounded_disconnect_buffered",
                        "download_saved_to_disk": False,
                    }
                )
            )
    finally:
        held.set()
        stop.set()
        if thread.ident is not None:
            thread.join(timeout=10)
            assert not thread.is_alive()
        with broker.connection_for_write() as connection:
            channel = connection.channel()
            try:
                channel.queue_delete(queue=cfg.queue)
                channel.exchange_delete(exchange=cfg.queue)
            finally:
                channel.close()
        broker.close()
