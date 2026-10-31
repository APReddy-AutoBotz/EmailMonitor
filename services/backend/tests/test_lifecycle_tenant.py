"""Actual disposable-PG lifecycle fences; all records are authored synthetic fixtures."""

import hashlib
from uuid import uuid4

import pytest
from emailmonitor.extraction.fixture import article_bytes
from emailmonitor.extraction.html import parse_article
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.lifecycle.models import (
    DeletionRequest,
    Retention,
    RetentionUpdate,
    SupportCreate,
    SuppressionCreate,
)
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.results.models import Filters
from emailmonitor.results.render import render
from emailmonitor.runtime.access import WorkAuthority
from sqlalchemy import create_engine, text
from test_association_tenant import client as fixture_client
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import ready as observation_ready
from test_progress_tenant import claim, planned
from test_results_tenant import lease, options, prepared, ready
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def lifecycle(s: Scenario, token: WorkAuthority) -> Lifecycle:
    return Lifecycle(s.foundation.database, token, SETTINGS)


def test_real_staged_job_deletion_invalidates_download_and_purges_content(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    before = results.contacts(org, Filters(job_id=job))
    assert before.items
    service = lifecycle(scenario, results.token)
    receipt = service.stage(org, DeletionRequest(job_id=job, reason="owner_request"))
    assert receipt.stage == "fenced" and receipt.backup_replay_required
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    again = service.stage(org, DeletionRequest(job_id=job, reason="owner_request"))
    assert again == receipt
    purged = service.purge(org, receipt.id)
    assert purged.stage == "purged" and purged.purged_at is not None
    assert service.purge(org, receipt.id) == purged
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            for table in (
                "discovery",
                "discovery_outbox",
                "article_observations",
                "association_batches",
            ):
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": job},
                    ).scalar_one()
                    == 0
                )
            assert (
                c.execute(
                    text(
                        "SELECT selected_urls FROM emailmonitor.execution_runs "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                is None
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.source_resource_requests "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 0
            )
            assert c.execute(
                text(
                    "SELECT request FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one() == {"lifecycle": "content_removed"}
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.export_artifacts "
                        "WHERE organization_id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text("SELECT count(*) FROM emailmonitor.lifecycle_purge_context")
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


def test_real_deletion_during_parse_cannot_commit_after_purge(scenario: Scenario) -> None:
    extraction, job = observation_ready(scenario)
    org = scenario.organizations[0]
    url = "https://synthetic.publisher.example/article-a.html"
    payload = article_bytes("article-a.html")
    observation = parse_article(SETTINGS, url, payload)
    service = lifecycle(scenario, extraction.token)
    receipt = service.stage(org, DeletionRequest(job_id=job, reason="privacy_request"))
    service.purge(org, receipt.id)
    with pytest.raises(AuthorizationDenied):
        extraction.commit(
            org,
            job,
            observation,
            expected_revision=3,
            source_digest=hashlib.sha256(payload).hexdigest(),
        )
    # Replayed stale parsed bytes are still denied after process/service replacement.
    replacement = lifecycle(scenario, extraction.token)
    assert replacement.purge(org, receipt.id).stage == "purged"
    with pytest.raises(AuthorizationDenied):
        extraction.commit(
            org,
            job,
            observation,
            expected_revision=3,
            source_digest=hashlib.sha256(payload).hexdigest(),
        )


def test_real_running_lease_and_export_finish_cannot_resurrect(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4()))
    work = lease(results, org, export.id)
    artifact = render(work.snapshot)
    service = lifecycle(scenario, results.token)
    service.stage(org, DeletionRequest(job_id=job, reason="privacy_request"))
    assert results.finish(work, artifact) is False
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.export_artifacts "
                        "WHERE organization_id=:org AND export_id=:id"
                    ),
                    {"org": org, "id": export.id},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()
    with pytest.raises(AuthorizationDenied):
        results.download(org, export.id)


def test_real_checkpoint_lease_generation_fenced_before_completion(scenario: Scenario) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    receipt = lifecycle(scenario, progress.token).stage(
        org, DeletionRequest(job_id=job, reason="owner_request")
    )
    with bound(work.lease), pytest.raises(AuthorizationDenied):
        progress.process_fixture(work)
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_items "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 0
        )
    assert receipt.stage == "fenced"


@pytest.mark.parametrize("kind", ["contact", "domain"])
def test_real_contact_suppression_keeps_only_keyed_metadata_and_no_resurrection(
    scenario: Scenario,
    kind: str,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    address = results.contacts(org, Filters(job_id=job)).items[0].raw_address
    export = ready(results, org, job)
    service = lifecycle(scenario, results.token)
    suppression = service.suppress(
        org,
        SuppressionCreate.model_validate(
            {
                "kind": kind,
                "value": address if kind == "contact" else address.rsplit("@", 1)[1],
                "reason": "privacy_request",
            }
        ),
    )
    assert suppression.active and address not in suppression.model_dump_json()
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    assert not service.withdraw(org, suppression.id).active
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()
    # Withdrawal never unmasks previously retained/deleted content.
    assert service.tick(org) == 1
    assert service.tick(org) == 0


def test_real_source_suppression_stops_new_work_and_withdrawal_does_not_unfence(
    scenario: Scenario,
) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    service = lifecycle(scenario, progress.token)
    suppression = service.suppress(
        org,
        SuppressionCreate(kind="source", value="synthetic-publisher", reason="source_restriction"),
    )
    with pytest.raises(AuthorizationDenied):
        progress.snapshot(org, job)
    service.withdraw(org, suppression.id)
    with pytest.raises(AuthorizationDenied):
        progress.snapshot(org, job)
    assert service.tick(org) == 1


def test_real_retention_reduction_is_current_and_revision_fenced(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    service = lifecycle(scenario, results.token)
    old = service.retention(org)
    update = RetentionUpdate(
        expected_revision=old.revision,
        retention=Retention(contact_days=0, excerpt_days=0, export_hours=0),
    )
    current = service.update_retention(org, update)
    assert current.revision == old.revision + 1
    with pytest.raises(RevisionConflict):
        service.update_retention(org, update)
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    assert service.tick(org) == 1
    assert service.tick(org) == 0


def test_real_support_context_is_existing_membership_metadata_and_revocable(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    owner = lifecycle(scenario, results.token)
    with fixture_client(scenario) as client:
        scenario.login(client, "operator")
        operator = lifecycle(scenario, str(client.cookies[COOKIE]))
        grantee = scenario.identities["operator"]
        context = owner.approve_support(
            org,
            SupportCreate(grantee_id=grantee, job_id=job, minutes=4, reason="synthetic_incident"),
        )
        inspection = operator.inspect_support(org, context.id)
        assert not inspection.content_access and inspection.retained_observations > 0
        assert "email" not in inspection.model_dump_json()
        with pytest.raises(AuthorizationDenied):
            owner.inspect_support(org, context.id)
        owner.revoke_support(org, context.id)
        with pytest.raises(AuthorizationDenied):
            operator.inspect_support(org, context.id)
        with pytest.raises(AuthorizationDenied):
            operator.approve_support(
                org,
                SupportCreate(
                    grantee_id=grantee, job_id=job, minutes=1, reason="synthetic_incident"
                ),
            )


def test_real_lifecycle_api_has_current_csrf_role_and_cross_tenant_refusal(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    with fixture_client(scenario) as client:
        csrf = scenario.login(client, "operator")
        path = f"/api/v1/organizations/{org}/privacy/deletions"
        body = {"job_id": str(job), "reason": "owner_request"}
        assert (
            client.post(
                path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
            ).status_code
            == 404
        )
        csrf = scenario.login(client, "owner")
        assert client.post(path, json=body).status_code in (403, 404)
        denied = client.post(
            f"/api/v1/organizations/{scenario.organizations[1]}/privacy/deletions",
            json=body,
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert denied.status_code == 404
        success = client.post(path, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
        assert success.status_code == 201
        assert "raw_address" not in success.text


def test_real_selected_job_staging_receipt_is_idempotent_without_physical_purge(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    with fixture_client(scenario) as client:
        csrf = scenario.login(client, "owner")
        path = f"/api/v1/organizations/{org}/privacy/deletions"
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        first = client.post(
            path, json={"job_id": str(job), "reason": "owner_request"}, headers=headers
        )
        assert first.status_code == 201
        receipt = first.json()
        assert receipt["job_id"] == str(job) and receipt["organization_id"] == str(org)
        assert receipt["stage"] == "fenced" and receipt["purged_at"] is None
        assert receipt["backup_replay_required"] is True
        repeated = client.post(
            path, json={"job_id": str(job), "reason": "privacy_request"}, headers=headers
        )
        assert repeated.status_code == 201 and repeated.json() == receipt
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                > 0
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.deletion_tombstones "
                        "WHERE organization_id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.audit_events WHERE organization_id=:org "
                        "AND action='lifecycle.fenced' AND resource_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 1
            )
    finally:
        admin.dispose()


def test_real_runtime_cannot_read_keys_context_or_create_unreviewed_grants(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    lifecycle(scenario, results.token).retention(org)
    with results.database.tenant(results.token, org, Capability.READ_ORGANIZATION) as (c, _):
        for table in (
            "privacy_keys",
            "privacy_suppressions",
            "deletion_tombstones",
            "lifecycle_purge_context",
            "support_contexts",
        ):
            assert not c.execute(
                text("SELECT has_table_privilege(current_user,:table,'SELECT')"),
                {"table": "emailmonitor." + table},
            ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user,"
                "'emailmonitor.privacy_digest(uuid,text,text)','EXECUTE')"
            )
        ).scalar_one()
        assert not c.execute(
            text("SELECT emailmonitor.privacy_source_allowed(:other)"),
            {"other": scenario.organizations[1]},
        ).scalar_one()
        assert not c.execute(
            text("SELECT emailmonitor.privacy_payload_allowed(:other,CAST(:body AS jsonb))"),
            {"other": scenario.organizations[1], "body": "{}"},
        ).scalar_one()


def test_real_org_content_tombstone_is_bounded_and_new_job_restore_refuses(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    service = lifecycle(scenario, results.token)
    marker = service.stage(org, DeletionRequest(job_id=None, reason="owner_request"))
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters())
    assert service.purge(org, marker.id).stage == "purged"
    assert service.purge(org, marker.id).stage == "purged"
    # The original job UUID remains a content-free tombstone and cannot become new work.
    with pytest.raises(AuthorizationDenied):
        results.outcomes(org, job)


def test_real_due_tick_is_atomic_replay_safe_and_current_owner_only(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    service = lifecycle(scenario, results.token)
    old = service.retention(org)
    service.update_retention(
        org, RetentionUpdate(expected_revision=old.revision, retention=Retention(contact_days=0))
    )
    events = service.schedule(org)
    assert len(events) == 1
    service.confirmed(org, events[0])
    assert service.schedule(org) == events
    assert service.scheduled_tick(org, events[0]) == 1
    assert service.scheduled_tick(org, events[0]) == 1
    assert service.schedule(org) == ()
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()


def test_real_privacy_digest_is_hmac_tenant_separated_and_never_exposed(scenario: Scenario) -> None:
    import hmac

    with fixture_client(scenario) as client:
        scenario.login(client, "owner")
        lifecycle(scenario, str(client.cookies[COOKIE])).retention(scenario.organizations[0])
        scenario.login(client, "owner_b")
        lifecycle(scenario, str(client.cookies[COOKIE])).retention(scenario.organizations[1])
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        digests = []
        with admin.connect() as c:
            for org in scenario.organizations:
                key: bytes = c.execute(
                    text("SELECT key FROM emailmonitor.privacy_keys WHERE organization_id=:org"),
                    {"org": org},
                ).scalar_one()
                actual: bytes = c.execute(
                    text("SELECT emailmonitor.privacy_digest(:org,'contact','Mira@Example.ORG')"),
                    {"org": org},
                ).scalar_one()
                expected = hmac.digest(
                    bytes(key), b"emailmonitor/privacy/v1/contact/mira@example.org", "sha256"
                )
                assert bytes(actual) == expected
                digests.append(bytes(actual))
            assert digests[0] != digests[1]
    finally:
        admin.dispose()


@pytest.mark.parametrize("loss", ["grantee_membership", "approver_identity"])
def test_real_support_expiry_and_membership_loss_refuse(scenario: Scenario, loss: str) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    owner = lifecycle(scenario, results.token)
    context = owner.approve_support(
        org,
        SupportCreate(
            grantee_id=scenario.identities["operator"],
            job_id=job,
            minutes=1,
            reason="synthetic_incident",
        ),
    )
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.support_contexts "
                    "SET created_at=clock_timestamp()-interval '2 hours',"
                    "expires_at=clock_timestamp()-interval '1 hour' "
                    "WHERE organization_id=:org AND id=:id"
                ),
                {"org": org, "id": context.id},
            )
        with fixture_client(scenario) as client:
            scenario.login(client, "operator")
            operator = lifecycle(scenario, str(client.cookies[COOKIE]))
            with pytest.raises(AuthorizationDenied):
                operator.inspect_support(org, context.id)
            current = owner.approve_support(
                org,
                SupportCreate(
                    grantee_id=scenario.identities["operator"],
                    job_id=job,
                    minutes=1,
                    reason="synthetic_incident",
                ),
            )
            with admin.begin() as c:
                if loss == "grantee_membership":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.memberships SET status='revoked' "
                            "WHERE organization_id=:org AND identity_id=:id"
                        ),
                        {"org": org, "id": scenario.identities["operator"]},
                    )
                else:
                    c.execute(
                        text("UPDATE emailmonitor.identities SET active=false WHERE id=:id"),
                        {"id": scenario.identities["owner"]},
                    )
            with pytest.raises(AuthorizationDenied):
                operator.inspect_support(org, current.id)
    finally:
        admin.dispose()


def test_real_probe_purge_releases_reserved_quota_without_changing_used(scenario: Scenario) -> None:
    from test_durable_jobs import approved

    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, version=1, count=2)
    service = lifecycle(scenario, ledger.token)
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        before = c.execute(
            text("SELECT reserved,used FROM emailmonitor.fixture_quota WHERE organization_id=:org"),
            {"org": org},
        ).one()
    assert before[0] == 2
    marker = service.stage(org, DeletionRequest(job_id=job, reason="owner_request"))
    service.purge(org, marker.id)
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        after = c.execute(
            text("SELECT reserved,used FROM emailmonitor.fixture_quota WHERE organization_id=:org"),
            {"org": org},
        ).one()
        assert after[0] == 0 and after[1] == before[1]


def test_real_retention_increase_never_unexpires_old_objects(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    service = lifecycle(scenario, results.token)
    old = service.retention(org)
    reduced = service.update_retention(
        org, RetentionUpdate(expected_revision=old.revision, retention=Retention(contact_days=0))
    )
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()
    service.update_retention(
        org, RetentionUpdate(expected_revision=reduced.revision, retention=Retention())
    )
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=job))
    assert results.contacts(org, Filters()).items == ()
    assert service.tick(org) == 1


@pytest.mark.parametrize("operation", ["create", "inspect"])
def test_real_support_identity_deactivation_lock_refuses_current_use(
    scenario: Scenario, operation: str
) -> None:
    from sqlalchemy.exc import DBAPIError

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    owner = lifecycle(scenario, results.token)
    request = SupportCreate(
        grantee_id=scenario.identities["operator"],
        job_id=job,
        minutes=1,
        reason="synthetic_incident",
    )
    context = owner.approve_support(org, request)
    with pytest.raises(AuthorizationDenied):
        owner.approve_support(
            org, request.model_copy(update={"grantee_id": scenario.identities["owner_b"]})
        )
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with fixture_client(scenario) as client:
            scenario.login(client, "operator")
            operator = lifecycle(scenario, str(client.cookies[COOKIE]))
            identity = scenario.identities["operator" if operation == "create" else "owner"]
            with admin.connect() as blocker:
                transaction = blocker.begin()
                blocker.execute(
                    text("UPDATE emailmonitor.identities SET active=false WHERE id=:id"),
                    {"id": identity},
                )
                with pytest.raises((AuthorizationDenied, DBAPIError)):
                    if operation == "create":
                        owner.approve_support(org, request)
                    else:
                        operator.inspect_support(org, context.id)
                transaction.commit()
            with pytest.raises(AuthorizationDenied):
                if operation == "create":
                    owner.approve_support(org, request)
                else:
                    operator.inspect_support(org, context.id)
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    "address,allowed",
    [
        ("Mira.Rao@Example.ORG", True),
        ("a+tag@example.org", True),
        ("a..b@example.org", False),
        ("a" * 65 + "@example.org", False),
        ("a@" + "b" * 64 + ".org", False),
        ("a@-example.org", False),
        ("a@example.org\n", False),
        ("a@exämple.org", False),
    ],
)
def test_real_runtime_privacy_payload_matches_python_grammar(
    scenario: Scenario, address: str, allowed: bool
) -> None:
    import json

    from emailmonitor.lifecycle.models import canonical_privacy

    results, _ = prepared(scenario)
    org = scenario.organizations[0]
    lifecycle(scenario, results.token).suppress(
        org, SuppressionCreate(kind="contact", value="other@example.org", reason="privacy_request")
    )
    try:
        canonical_privacy("contact", address)
        python_allowed = True
    except ValueError:
        python_allowed = False
    assert python_allowed is allowed
    with results.database.tenant(results.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
        assert (
            c.execute(
                text("SELECT emailmonitor.privacy_payload_allowed(:org,CAST(:body AS jsonb))"),
                {"org": org, "body": json.dumps({"candidate": {"raw_address": address}})},
            ).scalar_one()
            is allowed
        )


@pytest.mark.parametrize("boundary", ["entitlement", "completion"])
def test_real_final_release_authority_serializes_with_privacy_tombstone(
    scenario: Scenario, boundary: str
) -> None:
    import time

    from emailmonitor.administration.source import SourceAdmission
    from emailmonitor.fetching.safety import FetchDenied, classify_url
    from emailmonitor.sources.policy import Operation
    from sqlalchemy.exc import DBAPIError

    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    source = SourceAdmission(progress.database, progress.token, progress.settings)
    lease = source.acquire(
        org,
        1,
        Operation.HTML,
        classify_url(
            "https://synthetic.publisher.example/article-a.html",
            frozenset({"synthetic.publisher.example"}),
        ),
        time.monotonic() + 15,
    )
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        # A final entitlement decision retains its organization SHARE until commit.
        with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            assert (
                c.execute(
                    text("SELECT emailmonitor.network_entitlement_allowed(:org,'fetch_html',NULL)"),
                    {"org": org},
                ).scalar_one()
                is True
            )
            with admin.connect() as deleting:
                transaction = deleting.begin()
                deleting.execute(text("SET LOCAL lock_timeout='100ms'"))
                with pytest.raises(DBAPIError):
                    deleting.execute(
                        text(
                            "UPDATE emailmonitor.organizations SET display_name=display_name "
                            "WHERE id=:org"
                        ),
                        {"org": org},
                    )
                transaction.rollback()
        # Inverse ordering: a privacy transaction already owns UPDATE; refusal is immediate.
        with admin.connect() as deleting:
            transaction = deleting.begin()
            deleting.execute(
                text(
                    "UPDATE emailmonitor.organizations SET display_name=display_name WHERE id=:org"
                ),
                {"org": org},
            )
            if boundary == "completion":
                with pytest.raises(FetchDenied):
                    source.finish(lease, 200)
            else:
                with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (
                    c,
                    _,
                ):
                    assert (
                        c.execute(
                            text(
                                "SELECT emailmonitor.network_entitlement_allowed("
                                ":org,'fetch_html',NULL)"
                            ),
                            {"org": org},
                        ).scalar_one()
                        is False
                    )
            transaction.rollback()
        receipt = lifecycle(scenario, progress.token).stage(
            org, DeletionRequest(job_id=None, reason="privacy_request")
        )
        assert receipt.stage == "fenced"
        with pytest.raises(FetchDenied):
            source.finish(lease, 200)
        with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            assert (
                c.execute(
                    text("SELECT emailmonitor.network_entitlement_allowed(:org,'fetch_html',NULL)"),
                    {"org": org},
                ).scalar_one()
                is False
            )
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    "role", ["owner", "data_steward", "admin", "operator", "reviewer", "viewer"]
)
def test_contextual_suppression_api_uses_existing_management_capability(
    scenario: Scenario, role: str
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    contact = results.contacts(org, Filters(job_id=job)).items[0]
    with fixture_client(scenario) as client:
        csrf = scenario.login(client, role)
        prefix = f"/api/v1/organizations/{org}"
        detail = f"{prefix}/contacts/{contact.association_id}?batch_id={contact.batch_id}"
        assert client.get(detail).status_code == 200
        body = {"kind": "contact", "value": contact.raw_address, "reason": "privacy_request"}
        path = f"{prefix}/privacy/suppressions"
        # Neither a missing CSRF proof nor a different tenant may authorize the action.
        assert client.post(path, json=body).status_code in (403, 404)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        assert (
            client.post(
                path.replace(str(org), str(scenario.organizations[1])),
                json=body,
                headers=headers,
            ).status_code
            == 404
        )
        response = client.post(path, json=body, headers=headers)
        if role in ("owner", "data_steward"):
            assert response.status_code == 201
            assert response.json()["active"] is True
            assert response.json()["kind"] == "contact"
            assert contact.raw_address not in response.text
            assert client.get(detail).status_code == 404
        else:
            assert response.status_code == 404
            assert client.get(detail).status_code == 200


def test_ready_export_proof_precedes_contact_suppression_and_then_refuses(
    scenario: Scenario,
) -> None:
    import io
    from zipfile import ZipFile

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    address = results.contacts(org, Filters(job_id=job)).items[0].raw_address
    export = ready(results, org, job, optional_contact_fields=["article_title"])
    artifact = results.download(org, export)
    assert artifact.body.startswith(b"PK") and len(artifact.body) > 1000
    with ZipFile(io.BytesIO(artifact.body)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml")
    assert b">Affiliations<" not in sheet and b">Article title<" in sheet
    lifecycle(scenario, results.token).suppress(
        org,
        SuppressionCreate.model_validate(
            {
                "kind": "contact",
                "value": address,
                "reason": "privacy_request",
            }
        ),
    )
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    assert results.contacts(org, Filters()).items == ()
