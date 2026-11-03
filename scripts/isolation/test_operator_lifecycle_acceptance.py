"""Genuine guarded keyboard lifecycle → durable broker → retained export acceptance."""

import os
import threading
from pathlib import Path
from uuid import UUID

import pytest
from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.broker import publish
from emailmonitor.results.broker import publish as publish_exports
from emailmonitor.results.service import Results
from operator_ui_protocol import RequestFrame, asset_manifest
from run_operator_ui_acceptance import run
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_operator_lifecycle_tenant import article_work, failed_job, retained_job
from test_real_broker_jobs import config, wait_for, worker
from test_selection_handoff_tenant import rows
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

ROOT = Path(__file__).resolve().parents[2]


def verify_lifecycle_export(results: Results, org: UUID, cancel_job: UUID, retry_job: UUID) -> UUID:
    """Verify the original artifact before the later unlink intentionally fences it."""
    exports = results.exports(org)
    assert len(exports) == 1 and exports[0].state == "ready"
    artifact = rows(results.download(org, exports[0].id).body, "xlsx", False)
    assert len(artifact) == 2 and str(cancel_job) in artifact[1]
    assert str(retry_job) not in artifact[1]
    return exports[0].id


def test_required_connected_lifecycle_keyboard(scenario: Scenario, tmp_path: Path) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true"
    ):
        raise RuntimeError("Required reviewed disposable UI CI only")
    org, other = scenario.organizations
    progress, cancel_job = retained_job(scenario)
    old_lease = article_work(progress, org, cancel_job, "article-b.html")
    _, retry_job = failed_job(scenario, progress)
    original = progress.snapshot(org, retry_job)
    original_rows = progress.extraction.read(org, retry_job)
    with scenario.client() as other_owner:
        nonce = scenario.login(other_owner, "owner_b")
        response = other_owner.post(
            f"/api/v1/organizations/{other}/members",
            headers={"Origin": ORIGIN, "X-CSRF-Token": nonce},
            json={"identity_id": str(scenario.identities["owner"]), "role": "viewer"},
        )
        assert response.status_code == 201
    app = create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation)
    with APIClient(app, ORIGIN) as owner:
        scenario.login(owner, "owner")
        cookies = [
            {
                "name": v.name,
                "value": v.value,
                "domain": "app.example.test",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Strict" if v.name.endswith("csrf") else "Lax",
            }
            for v in owner.cookies.jar
        ]
    cfg = config(scenario, Ledger(progress.database, progress.token, SETTINGS), ui_diagnostics=True)
    broker, _ = create_worker(cfg)
    results = Results(progress.database, progress.token, SETTINGS)
    hold, held, released = threading.Event(), threading.Event(), threading.Event()
    replies: list[int] = []
    verified_exports: list[UUID] = []

    def child() -> UUID:
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
            return c.execute(
                text(
                    "SELECT job_id FROM emailmonitor.execution_runs "
                    "WHERE organization_id=:org AND retry_from=:job"
                ),
                {"org": org, "job": retry_job},
            ).scalar_one()

    def before_reply(request: RequestFrame) -> bool:
        if (
            hold.is_set()
            and request.method == "POST"
            and request.url.endswith(f"/jobs/{retry_job}/retry")
        ):
            held.set()
            if not released.wait(8):
                raise RuntimeError("Owned lifecycle response release deadline exceeded")
            replies.append(request.identifier)
        return False

    def control(action: str) -> None:
        if action == "hold_lifecycle_reply":
            hold.set()
        elif action == "wait_held":
            if not held.wait(8):
                raise RuntimeError("Owned lifecycle response not held")
        elif action == "release_lifecycle_reply":
            hold.clear()
            released.set()
        elif action == "publish":
            assert publish(broker, progress, org) == 1
        elif action == "wait_jobs":
            wait_for(lambda: progress.snapshot(org, child()).state == "completed", seconds=8)
        elif action == "wait_exports":
            assert publish_exports(broker, results, org) == 1
            wait_for(
                lambda: (
                    bool(results.exports(org))
                    and all(x.state == "ready" for x in results.exports(org))
                ),
                seconds=8,
            )
        elif action == "verify_retained":
            assert not verified_exports
            verified_exports.append(verify_lifecycle_export(results, org, cancel_job, retry_job))
        else:
            raise RuntimeError("Unexpected fixed lifecycle control")

    setup: dict[str, object] = {
        "kind": "bootstrap",
        "origin": ORIGIN,
        "journey": "controlled_lifecycle",
        "cookies": cookies,
        "assets": asset_manifest(ROOT / "apps/web/dist"),
        "initial_organization": str(org),
        "other_organization": str(other),
        "cancel_job": str(cancel_job),
        "retry_job": str(retry_job),
    }
    try:
        with worker(cfg, tmp_path):
            evidence = run(app, setup, control, before_reply)
        assert evidence["journey"] == "controlled_lifecycle"
        assert all(
            evidence[k] is True
            for k in (
                "keyboard",
                "confirmed_cancel",
                "retained_review_export",
                "continuation",
                "late_mutation_scope",
            )
        )
        assert evidence["network_errno"] == [101, 101] and evidence["interfaces"] == ["lo"]
        assert len(replies) == 1
        assert progress.snapshot(org, cancel_job).state == "cancelled"
        with pytest.raises(AuthorizationDenied):
            progress.finish(old_lease)
        assert progress.snapshot(org, retry_job) == original
        assert progress.extraction.read(org, retry_job) == original_rows
        assert progress.retry(org, retry_job, original.revision) == child()
        exports = results.exports(org)
        assert len(verified_exports) == 1
        assert len(exports) == 1 and exports[0].state == "ready"
        assert exports[0].id == verified_exports[0] and not exports[0].download_available
        with pytest.raises(AuthorizationDenied):
            results.download(org, exports[0].id)
    finally:
        released.set()
        with broker.connection_for_write() as connection:
            channel = connection.channel()
            try:
                for queue in owned_queues(cfg.queue):
                    channel.queue_delete(queue=queue)
                    channel.exchange_delete(exchange=queue)
            finally:
                channel.close()
        broker.close()
