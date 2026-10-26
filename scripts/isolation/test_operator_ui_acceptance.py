"""Required disposable CI: actual React → ASGI → PostgreSQL/outbox → broker/worker."""

import hashlib
import io
import json
import os
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

import pytest
from api_client import APIClient
from emailmonitor.administration.service import Administration
from emailmonitor.api import create_app
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.entitlement_diagnostics import snapshot as entitlement_snapshot
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.broker import publish as publish_execution
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import publish as publish_exports
from emailmonitor.results.service import Results
from entitlement_sql_diagnostic import entitlement_diagnostic
from operator_queue_probe import observe as observe_parse_queue
from operator_ui_protocol import (
    RequestFrame,
    asset_manifest,
    completion_failure_classes,
    completion_state_counts,
    completion_unit_counts,
    completion_worker_snapshot,
)
from run_operator_ui_acceptance import run
from sqlalchemy import create_engine, text
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import config, wait_for, worker
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def entitlement_trace(scenario: Scenario) -> Iterator[None]:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true"
    ):
        raise RuntimeError("Required reviewed disposable UI CI only")
    engine = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with entitlement_diagnostic(engine):
            yield
    finally:
        engine.dispose()


def test_required_actual_keyboard_operator_ui(
    scenario: Scenario, tmp_path: Path, entitlement_trace: None
) -> None:
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
    cfg = config(scenario, Ledger(progress.database, token, SETTINGS), ui_diagnostics=True)
    broker, _ = create_worker(cfg)
    stop, release = threading.Event(), threading.Event()
    errors: list[str] = []
    held, hold_contacts, fault_contacts = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    hold_quality, fault_quality = threading.Event(), threading.Event()
    quality_faults: list[int] = []
    quality_holds: list[int] = []
    held.set()
    observed_hold = threading.Event()
    hold_events = threading.Event()
    late_events: list[int] = []
    late_replies: list[int] = []
    faults: list[int] = []

    def before_reply(request: RequestFrame) -> bool:
        if request.method == "GET" and request.url.endswith("/observation-quality"):
            if fault_quality.is_set():
                fault_quality.clear()
                quality_faults.append(request.identifier)
                return True
            if hold_quality.is_set():
                observed_hold.set()
                if not held.wait(timeout=8):
                    raise RuntimeError("Owned quality response release deadline exceeded")
                quality_holds.append(request.identifier)
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

    retained_receipt: dict[str, object] = {}

    def verify_retained() -> None:
        assert not retained_receipt
        with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
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
                    "SELECT count(*) FROM emailmonitor.execution_effects WHERE organization_id=:org"
                ),
                {"org": org},
            ).scalar_one()
        assert (
            len(jobs) == 2 and jobs[0].state == "completed_partial" and jobs[1].state == "completed"
        )
        with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
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
        assert first.counts.by_outcome["unsupported"] == first.counts.by_outcome["no_contact"] == 1
        assert reviews == 1 and effects >= 5
        assert len(quality_faults) == len(quality_holds) == 1
        administration = Administration(progress.database, token, progress.settings)
        configuration = administration.read(org)
        usage = administration.usage(org)
        assert configuration.branding.label == "Keyboard authored workspace"
        assert configuration.branding.accent_color == "#123456" and configuration.revision == 2
        assert usage.settled_resolution_units == effects and usage.reserved_resolution_units == 0
        assert usage.source_resource_attempts == 0  # Authored file reads are not HTTP attempts.
        exports = results.exports(org)
        assert len(exports) == 1 and exports[0].state == "ready"
        artifact = results.download(org, exports[0].id)
        assert artifact.body.startswith(b"PK") and len(artifact.body) > 1000
        with ZipFile(io.BytesIO(artifact.body)) as archive:
            contact_sheet = archive.read("xl/worksheets/sheet1.xml")
        assert b">Affiliations<" not in contact_sheet and b">Article title<" in contact_sheet
        retained_receipt.update(
            export_id=exports[0].id,
            review_receipts=reviews,
            durable_effects=effects,
            export_sha256=hashlib.sha256(artifact.body).hexdigest(),
            export_bytes=len(artifact.body),
        )

    def control(action: str) -> None:
        if action == "publish":
            release.set()
        elif action == "fault_quality":
            fault_quality.set()
        elif action == "hold_quality":
            held.clear()
            observed_hold.clear()
            hold_quality.set()
        elif action == "release_quality":
            held.set()
            hold_quality.clear()
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
            observed_states: dict[str, int] = {}

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
                observed_states.clear()
                observed_states.update(completion_state_counts(list(rows)))
                return bool(rows) and all(
                    value in {"completed", "completed_partial", "failed", "cancelled"}
                    for value in rows
                )

            try:
                wait_for(complete, seconds=8)
            except AssertionError:
                with progress.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
                    units = completion_unit_counts(
                        [
                            dict(row)
                            for row in c.execute(
                                text("""
SELECT i.work_kind AS kind, i.state, i.reason, i.attempts,
COALESCE(i.lease_until>clock_timestamp(),false) AS lease_live,
COALESCE(o.published_at IS NOT NULL,false) AS published
FROM emailmonitor.execution_items i
JOIN emailmonitor.jobs j ON j.organization_id=i.organization_id AND j.id=i.job_id
LEFT JOIN emailmonitor.execution_outbox o ON o.organization_id=i.organization_id
AND o.job_id=i.job_id AND o.item_id=i.id AND o.generation=j.generation
WHERE i.organization_id=:org AND j.kind='extraction' LIMIT 33
"""),
                                {"org": org},
                            ).mappings()
                        ]
                    )
                logs = list(tmp_path.glob(cfg.queue + "-*.log"))
                if (
                    len(logs) != 1
                    or logs[0].is_symlink()
                    or logs[0].resolve().parent != tmp_path.resolve()
                ):
                    raise RuntimeError("Exact owned worker log required") from None
                with logs[0].open("rb") as file:
                    file.seek(0, 2)
                    truncated = file.tell() > 65536
                    file.seek(max(0, file.tell() - 65536))
                    tail = file.read(65536)
                    failure_classes = completion_failure_classes(tail)
                    worker_snapshot = completion_worker_snapshot(tail, truncated=truncated)
                queue_counts = observe_parse_queue(cfg.broker_url, cfg.queue)
                print(
                    "operator-ui-control:wait_jobs "
                    + json.dumps(
                        {
                            "states": observed_states,
                            "publisher_failed": bool(errors),
                            "worker_live": worker_process.poll() is None,
                            "owned_parse_queue": queue_counts,
                            "units": units,
                            "matched_worker_failure_classes": failure_classes,
                            "worker_stages": worker_snapshot,
                            "entitlement_invocations": entitlement_snapshot(
                                tail, truncated=truncated
                            ),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                raise
        elif action == "verify_retained":
            verify_retained()
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
        with worker(cfg, tmp_path) as worker_process:

            def consumer_ready() -> bool:
                with broker.connection_for_read() as connection:
                    channel = connection.channel()
                    try:
                        return bool(
                            all(
                                channel.queue_declare(queue=q, passive=True).consumer_count > 0
                                for q in owned_queues(cfg.queue)
                            )
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
                    "actual_zero_contact_quality_dialog",
                    "actual_terminal_replay_render_ready",
                    "delayed_terminal_replay_render_proof",
                    "authored_127_outcome_paging",
                    "review",
                    "pause_resume_cancel_dismiss",
                    "dialog_focus_restore",
                    "optional_field_preview",
                    "usage_audit_settings",
                    "download_cancelled",
                    "org_switch",
                    "readonly_role",
                    "contact_suppression",
                ]
            )
            assert evidence["network_errno"] == [101, 101] and evidence["interfaces"] == ["lo"]
            assert retained_receipt
            with pytest.raises(AuthorizationDenied):
                results.download(org, UUID(str(retained_receipt["export_id"])))

            print(
                json.dumps(
                    {
                        **evidence,
                        "actual_postgresql": True,
                        "actual_broker_worker": True,
                        **{
                            key: value
                            for key, value in retained_receipt.items()
                            if key != "export_id"
                        },
                        "export_refused_after_suppression": True,
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
                for queue in owned_queues(cfg.queue):
                    channel.queue_delete(queue=queue)
                    channel.exchange_delete(exchange=queue)
            finally:
                channel.close()
        broker.close()
        observed = entitlement_snapshot(b"")
        try:
            logs = list(tmp_path.glob(cfg.queue + "-*.log"))
            if (
                len(logs) != 1
                or logs[0].is_symlink()
                or logs[0].resolve().parent != tmp_path.resolve()
            ):
                raise RuntimeError("Exact owned worker log required")
            with logs[0].open("rb") as stream:
                stream.seek(0, 2)
                truncated = stream.tell() > 65536
                stream.seek(max(0, stream.tell() - 65536))
                observed = entitlement_snapshot(stream.read(65536), truncated=truncated)
        except Exception:
            # Preserve the original worker failure; successful runs require completeness below.
            pass
        print("operator-entitlement-invocations " + json.dumps(observed), flush=True)
    assert observed["complete"] is True
