"""Actual fixed sandbox output feeds durable tenant review and both export formats.

Missing disposable services are skips locally. CI sets EM_REQUIRE_XML_ISOLATION,
builds the reviewed image and cannot substitute a host parse or skip these checks.
"""

import io
import json
import os
from collections.abc import Iterator, Mapping
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.xml_retained import XML_URL, RetainedXml, retain_xml
from emailmonitor.extraction.xml_service import XmlExtraction
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import (
    DeletionRequest,
    Retention,
    RetentionUpdate,
    SuppressionCreate,
)
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress, Work
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim
from test_results_tenant import ready
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def planned_xml(s: Scenario, *, excerpts: bool = True, html: bool = False) -> tuple[Progress, UUID]:
    operations = ["fetch_html" if html else "fetch_xml", "extract_contacts", "export_contacts"]
    if excerpts:
        operations.append("retain_excerpt")
    with s.client() as client:
        csrf = s.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(s)
        policy = policy_body(
            allowed_operations=operations,
            retention={"raw_hours": 0, "excerpt_days": 30 if excerpts else 0, "contact_days": 90},
        )
        response = client.post(
            path + "/policies", headers=headers, json={"expected_version": 0, "policy": policy}
        )
        assert response.status_code == 201, response.text
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        ledger = Ledger(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
    body = request_body()
    body["input"] = {"type": "url", "url": XML_URL}
    job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    discovery.plan(s.organizations[0], job, 1)
    return Progress(ledger.database, ledger.token, SETTINGS), job


def running(s: Scenario, *, excerpts: bool = True) -> tuple[Progress, UUID, Work]:
    progress, job = planned_xml(s, excerpts=excerpts)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    return progress, job, claim(progress, org, job)


@pytest.fixture
def require_isolation() -> Iterator[None]:
    if os.environ.get("EM_REQUIRE_XML_ISOLATION") != "true":
        pytest.skip("Actual reviewed Docker parser image required for XML tenant acceptance")
    yield


def test_actual_container_output_persists_review_and_both_exports(
    scenario: Scenario,
    require_isolation: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emailmonitor.parsing import xml_channel

    profiles: list[Mapping[str, object]] = []
    original_verify = xml_channel.verify_profile

    def verified(metadata: Mapping[str, object]) -> None:
        original_verify(metadata)
        profiles.append(metadata)

    monkeypatch.setattr(xml_channel, "verify_profile", verified)
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    assert progress.process_fixture(work) == "needs_review"
    snapshots = progress.extraction.read(org, job)
    assert len(snapshots) == 1
    retained = RetainedXml.model_validate_json(json.dumps(snapshots[0]["observation"]))
    assert retained.binding.item == work.lease.item and retained.url == XML_URL
    assert (
        retained.canonical_url == "https://api.elsevier.com/content/article/doi/10.9999/synthetic.1"
    )
    batch = progress.items(org, job)[0].batch_id
    assert batch is not None
    bundle = progress.associations.detail(org, batch)
    assert {a.state for a in bundle.associations} == {"needs_review"}
    results = Results(progress.database, progress.token, SETTINGS)
    assert results.contacts(org, Filters(job_id=job)).items == ()
    candidate = next(c for c in bundle.candidates if c.address.raw_address == "Second@example.org")
    association = next(a for a in bundle.associations if a.candidate_id == candidate.id)
    reviewed = progress.associations.review(
        org,
        batch,
        Review(
            association_id=association.id,
            expected_revision=association.revision,
            action="accept",
            evidence_ids=association.evidence_ids,
            reason="Inspected retained XML author/address evidence",
        ),
    )
    assert next(a for a in reviewed.associations if a.id == association.id).state == "accepted"
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == 1 and contacts[0].technical_status == "not_checked"
    assert contacts[0].outreach_eligibility == "not_assessed"
    assert contacts[0].source_url == XML_URL
    exports = []
    for format in ("csv", "xlsx"):
        export = ready(results, org, job, format=format)
        artifact = results.download(org, export)
        assert artifact.body
        if format == "csv":
            assert artifact.extension == "zip"
            with ZipFile(io.BytesIO(artifact.body)) as archive:
                assert b"Second@example.org" in archive.read("contacts.csv")
        else:
            with ZipFile(io.BytesIO(artifact.body)) as archive:
                assert any(
                    b"Second@example.org" in archive.read(name)
                    for name in archive.namelist()
                    if name.startswith("xl/worksheets/")
                )
        exports.append(export)
    with scenario.client() as client:
        scenario.login(client, "owner_b")
        other_token = str(client.cookies[COOKIE])
        other = Results(progress.database, other_token, SETTINGS)
        other_progress = Progress(progress.database, other_token, SETTINGS)
        for target_org in (org, scenario.organizations[1]):
            with pytest.raises(AuthorizationDenied):
                other_progress.extraction.read(target_org, job)
            with pytest.raises(AuthorizationDenied):
                other_progress.associations.detail(target_org, batch)
            with pytest.raises(AuthorizationDenied):
                other_progress.associations.review(
                    target_org,
                    batch,
                    Review(
                        association_id=association.id,
                        expected_revision=2,
                        action="accept",
                        evidence_ids=association.evidence_ids,
                        reason="Other tenant must not review",
                    ),
                )
        for export in exports:
            with pytest.raises(AuthorizationDenied):
                other.download(org, export)
        with pytest.raises(AuthorizationDenied):
            other.contacts(scenario.organizations[1], Filters(job_id=job))
    # Reviewed rows remain stable on duplicate delivery; no additional effect/unit.
    assert progress.claim(org, job, work.lease.item, uuid4()) is None
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects WHERE "
                    "organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 1
        )
    assert len(profiles) == 1
    checked = profiles[0]["HostConfig"]
    assert isinstance(checked, dict)
    with capsys.disabled():
        print(
            json.dumps(
                {
                    "proof": "XML_SAME_CONTAINER_DATABASE_REVIEW_EXPORT",
                    "image": profiles[0]["Image"],
                    "network": checked["NetworkMode"],
                    "readonly": checked["ReadonlyRootfs"],
                    "memory": checked["Memory"],
                    "pids": checked["PidsLimit"],
                    "caps": checked["CapDrop"],
                    "digest": retained.content_digest,
                    "authors": 3,
                    "candidates": 2,
                    "accepted": 1,
                    "formats": ["csv", "xlsx"],
                    "tenant_b": "denied",
                    "effects": 1,
                }
            ),
            flush=True,
        )


def test_actual_xml_no_excerpt_policy_never_accepts(
    scenario: Scenario, require_isolation: None
) -> None:
    progress, job, work = running(scenario, excerpts=False)
    org = scenario.organizations[0]
    assert progress.process_fixture(work) == "needs_review"
    batch = progress.items(org, job)[0].batch_id
    assert batch is not None
    bundle = progress.associations.detail(org, batch)
    assert all(not e.excerpt for e in bundle.evidence)
    association = bundle.associations[0]
    with pytest.raises(ValueError, match="retained"):
        progress.associations.review(
            org,
            batch,
            Review(
                association_id=association.id,
                expected_revision=1,
                action="accept",
                evidence_ids=association.evidence_ids,
                reason="Missing source excerpt",
            ),
        )
    assert (
        Results(progress.database, progress.token, SETTINGS)
        .contacts(org, Filters(job_id=job))
        .items
        == ()
    )


def mutate_authority(s: Scenario, progress: Progress, job: UUID, kind: str) -> None:
    org = s.organizations[0]
    lifecycle = Lifecycle(progress.database, progress.token, SETTINGS)
    if kind in ("cancel", "pause"):
        progress.control(
            org,
            job,
            progress.snapshot(org, job).revision,
            "cancel" if kind == "cancel" else "pause",
        )
    elif kind == "delete":
        lifecycle.stage(org, DeletionRequest(job_id=job, reason="privacy_request"))
    elif kind == "suppression":
        lifecycle.suppress(
            org,
            SuppressionCreate(kind="contact", value="Second@example.org", reason="privacy_request"),
        )
    elif kind == "retention":
        current = lifecycle.retention(org)
        lifecycle.update_retention(
            org,
            RetentionUpdate(
                expected_revision=current.revision, retention=Retention(excerpt_days=0)
            ),
        )
    else:
        admin = create_engine(s.admin_url)
        try:
            with admin.begin() as c:
                if kind == "expired_lease":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.execution_items SET "
                            "lease_until=clock_timestamp()-interval '1 second' WHERE "
                            "organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": job},
                    )
                elif kind == "lost_lease":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.execution_items SET lease_token=:token WHERE "
                            "organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": job, "token": uuid4()},
                    )
                elif kind == "revoked_policy":
                    # A newly revoked source cannot release a previously parsed result.
                    c.execute(
                        text(
                            "UPDATE emailmonitor.source_policies SET state='revoked' WHERE "
                            "organization_id=:org AND source_id='synthetic-publisher' AND version=1"
                        ),
                        {"org": org},
                    )
                elif kind == "expired_session":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.sessions SET "
                            "expires_at=clock_timestamp()-interval '1 second' WHERE "
                            "identity_id=:identity"
                        ),
                        {"identity": s.identities["owner"]},
                    )
                elif kind == "revoked_session":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() "
                            "WHERE identity_id=:identity"
                        ),
                        {"identity": s.identities["owner"]},
                    )
                else:
                    raise AssertionError("Unknown authority mutation")
        finally:
            admin.dispose()


@pytest.mark.parametrize(
    "kind",
    [
        "cancel",
        "pause",
        "delete",
        "suppression",
        "retention",
        "expired_lease",
        "lost_lease",
        "revoked_policy",
        "revoked_session",
        "expired_session",
    ],
)
def test_actual_parser_result_cannot_commit_after_authority_changes(
    scenario: Scenario, require_isolation: None, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from emailmonitor.extraction import xml_service

    progress, job, work = running(scenario)
    from emailmonitor.parsing.xml_channel import parse_isolated

    original = parse_isolated

    def changed(settings: object, data: bytes) -> object:
        observed = original(SETTINGS, data)
        mutate_authority(scenario, progress, job, kind)
        return observed

    monkeypatch.setattr(xml_service, "parse_isolated", changed)
    with pytest.raises((AuthorizationDenied, DBAPIError, HTTPException)):
        progress.process_fixture(work)
    admin = create_engine(scenario.admin_url)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations WHERE "
                        "organization_id=:org AND job_id=:job"
                    ),
                    {"org": scenario.organizations[0], "job": job},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    "field",
    [
        "organization",
        "job",
        "item",
        "generation",
        "deletion_generation",
        "policy_version",
        "discovery_revision",
    ],
)
def test_actual_result_binding_mismatch_refused(
    scenario: Scenario, require_isolation: None, field: str
) -> None:
    from emailmonitor.extraction.xml_service import fixture_bytes
    from emailmonitor.parsing.xml_channel import parse_isolated

    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    service = XmlExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = service.binding(org, job, work.discovery_revision)
        observed = parse_isolated(SETTINGS, fixture_bytes())
        wrong = binding.model_copy(
            update={field: uuid4() if field in ("organization", "job", "item") else 999}
        )
        value = retain_xml(observed, wrong, excerpts)
        with pytest.raises(AuthorizationDenied):
            service.commit_xml(org, job, value)


def test_xml_requires_explicit_operation_and_xml_only_refuses_html(scenario: Scenario) -> None:
    progress, job = planned_xml(scenario)
    org = scenario.organizations[0]
    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/article-a.html"}
    other = Ledger(progress.database, progress.token, SETTINGS).create(
        org, JobRequest.model_validate(body), str(uuid4())
    )
    with pytest.raises(AuthorizationDenied):
        progress.discovery.plan(org, other, 1)
    assert progress.snapshot(org, job).unique_articles == 1


def test_html_policy_cannot_plan_xml(scenario: Scenario) -> None:
    with pytest.raises(AuthorizationDenied):
        planned_xml(scenario, html=True)


def test_actual_committed_xml_recovers_after_lost_completion(
    scenario: Scenario, require_isolation: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from emailmonitor.extraction import xml_service

    progress, job, work = running(scenario)
    org = scenario.organizations[0]

    def interrupted() -> None:
        raise RuntimeError("Synthetic interruption after observation commit")

    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        progress.process_fixture(work, after_observation=interrupted)
    assert len(progress.extraction.read(org, job)) == 1
    assert progress.finish(work, failure="worker_failure") == "retry_wait"
    recovered = claim(progress, org, job)

    def no_reparse(*args: object) -> None:
        raise AssertionError("Committed XML must recover without parser replay")

    monkeypatch.setattr(xml_service, "parse_isolated", no_reparse)
    assert progress.process_fixture(recovered) == "needs_review"
    assert len(progress.extraction.read(org, job)) == 1
    assert len(progress.associations.batches(org, job)) == 1
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects WHERE "
                    "organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.resolution_accounts WHERE "
                    "organization_id=:org AND root_job_id=:job AND state='settled'"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 1
        )


def test_preparse_authority_refusal_never_reads_xml_bytes(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    from emailmonitor.extraction import xml_service

    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    progress.control(org, job, progress.snapshot(org, job).revision, "cancel")

    def denied_bytes() -> bytes:
        raise AssertionError("Revoked work reached authored bytes")

    monkeypatch.setattr(xml_service, "fixture_bytes", denied_bytes)
    with bound(work.lease), pytest.raises(AuthorizationDenied):
        XmlExtraction(progress.database, progress.token, SETTINGS).isolated_fixture(
            org, job, work.discovery_revision
        )
