"""OA-029: Open Access JATS results persist through the durable review/export model.

Real PostgreSQL (disposable, synthetic). The isolated-container test runs only where
CI sets ``EM_REQUIRE_XML_ISOLATION``; every other test injects the same JATS parser
in-process so the database guards, tenancy, review and export paths are exercised
on every machine with the disposable database.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterator
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.config import Settings
from emailmonitor.discovery.openaccess_orchestrator import OpenAccessOrchestrator
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.jats import JatsObservation, parse_jats_xml
from emailmonitor.extraction.jats_retained import RetainedJats, retain_jats
from emailmonitor.extraction.jats_service import OaExtraction
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import SuppressionCreate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.parsing.jats_protocol import JatsExpectation
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress, Work
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from emailmonitor.sources import open_access_documents as registry
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

PLOS = registry.BY_URL["https://synthetic.publisher.example/oa/PMC10293847.xml"]
USHER = registry.BY_URL["https://synthetic.publisher.example/oa/PMC7700001.xml"]
NO_CONTACT = registry.BY_URL["https://synthetic.publisher.example/oa/PMC887766.xml"]
PLOS_ADDRESS = "marcus.vance@biotech.zurich.example"


def host_parser(settings: Settings, data: bytes, expected: JatsExpectation) -> JatsObservation:
    """In-process stand-in for the sandbox; same protocol checks, test-only."""
    expected.check_bytes(data)
    observed = parse_jats_xml(data, expected.requested_identifier)
    expected.check_observation(observed)
    return observed


def planned(
    s: Scenario,
    url: str = PLOS.source_url,
    *,
    excerpts: bool = True,
    operation: str = "fetch_xml",
) -> tuple[Progress, UUID]:
    operations = [operation, "extract_contacts", "export_contacts"]
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
    body["input"] = {"type": "url", "url": url}
    job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
    Discovery(ledger.database, ledger.token, SETTINGS).plan(s.organizations[0], job, 1)
    return Progress(ledger.database, ledger.token, SETTINGS), job


def running(
    s: Scenario, url: str = PLOS.source_url, *, excerpts: bool = True
) -> tuple[Progress, UUID, Work]:
    progress, job = planned(s, url, excerpts=excerpts)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    return progress, job, claim(progress, org, job)


def stored(progress: Progress, org: UUID, job: UUID) -> dict[str, object]:
    observation = progress.extraction.read(org, job)[0]["observation"]
    assert isinstance(observation, dict)
    return observation


def observation_count(s: Scenario, job: UUID) -> int:
    admin = create_engine(s.admin_url)
    try:
        with admin.connect() as c:
            return int(
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations WHERE "
                        "organization_id=:org AND job_id=:job"
                    ),
                    {"org": s.organizations[0], "job": job},
                ).scalar_one()
            )
    finally:
        admin.dispose()


@pytest.fixture
def require_isolation() -> Iterator[None]:
    if os.environ.get("EM_REQUIRE_XML_ISOLATION") != "true":
        pytest.skip("Actual reviewed Docker parser image required for isolated JATS acceptance")
    yield


# ------------------------------------------------------------ end-to-end path


def test_open_access_article_persists_waits_for_review_and_exports(scenario: Scenario) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    messages = [row for row in progress.pending(org) if row["job_id"] == job]
    assert len(messages) == 1
    event = UUID(str(messages[0]["event_id"]))
    item = UUID(str(messages[0]["item_id"]))
    generation = int(str(messages[0]["generation"]))
    work = progress.claim(org, job, item, event, generation=generation)
    assert work is not None
    assert progress.process_fixture(work, jats_parser=host_parser) == "needs_review"

    snapshots = progress.extraction.read(org, job)
    assert len(snapshots) == 1
    retained = RetainedJats.model_validate_json(json.dumps(snapshots[0]["observation"]))
    assert retained.url == PLOS.source_url and retained.route == "jats_xml"
    assert retained.canonical_url == PLOS.canonical_url
    assert retained.content_digest == PLOS.content_digest
    assert retained.binding.item == item
    assert retained.license_category == "unknown"
    assert "oa-" not in json.dumps(snapshots[0]["observation"])  # no cross-tenant contact id

    batch = progress.items(org, job)[0].batch_id
    assert batch is not None
    bundle = progress.associations.detail(org, batch)
    assert bundle.observation_route == "jats_xml"
    # No automatic acceptance for Open Access JATS.
    assert {a.state for a in bundle.associations} <= {"needs_review", "unmatched"}
    quality = progress.associations.quality(org, batch)
    assert quality.observation_route == "jats_xml" and quality.reason_availability == "recorded"

    results = Results(progress.database, progress.token, SETTINGS)
    assert results.contacts(org, Filters(job_id=job)).items == ()
    candidate = next(c for c in bundle.candidates if c.address.raw_address == PLOS_ADDRESS)
    association = next(
        a for a in bundle.associations if a.candidate_id == candidate.id and a.author_id
    )
    reviewed = progress.associations.review(
        org,
        batch,
        Review(
            association_id=association.id,
            expected_revision=association.revision,
            action="accept",
            evidence_ids=association.evidence_ids,
            reason="Inspected retained JATS author/address evidence",
        ),
    )
    assert next(a for a in reviewed.associations if a.id == association.id).state == "accepted"
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == 1
    assert contacts[0].source_url == PLOS.source_url
    assert contacts[0].technical_status == "not_checked"
    assert contacts[0].outreach_eligibility == "not_assessed"
    # "Allow but flag": the article licence travels with the reviewed contact.
    assert contacts[0].license_category == "unknown"
    export = ready(results, org, job, format="csv")
    artifact = results.download(org, export)
    with ZipFile(io.BytesIO(artifact.body)) as archive:
        sheet = archive.read("contacts.csv")
        assert PLOS_ADDRESS.encode() in sheet
        assert b"Article licence" in sheet.splitlines()[0]
        assert sheet.splitlines()[1].endswith(b',"unknown"')

    # Tenant B sees nothing and cannot act on tenant A's rows.
    with scenario.client() as client:
        scenario.login(client, "owner_b")
        other_token = str(client.cookies[COOKIE])
        other_progress = Progress(progress.database, other_token, SETTINGS)
        other_results = Results(progress.database, other_token, SETTINGS)
        for target in (org, scenario.organizations[1]):
            with pytest.raises(AuthorizationDenied):
                other_progress.extraction.read(target, job)
            with pytest.raises(AuthorizationDenied):
                other_progress.associations.detail(target, batch)
        with pytest.raises(AuthorizationDenied):
            other_results.download(org, export)
        with pytest.raises(AuthorizationDenied):
            other_results.contacts(scenario.organizations[1], Filters(job_id=job))

    # Duplicate delivery of the original event is a no-op; a forged event is denied.
    assert progress.claim(org, job, item, event, generation=generation) is None
    with pytest.raises(DBAPIError):
        progress.claim(org, job, item, uuid4(), generation=generation)
    assert len(progress.extraction.read(org, job)) == 1
    assert len(progress.associations.batches(org, job)) == 1
    assert len(results.contacts(org, Filters(job_id=job)).items) == 1
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


def test_no_contact_article_completes_without_candidates(scenario: Scenario) -> None:
    progress, job, work = running(scenario, NO_CONTACT.source_url)
    assert progress.process_fixture(work, jats_parser=host_parser) == "no_contact"
    observation = stored(progress, scenario.organizations[0], job)
    assert observation["status"] == "no_contact" and observation["candidates"] == []


def test_persisted_pairs_match_the_in_memory_pipeline(scenario: Scenario) -> None:
    progress, job, work = running(scenario, USHER.source_url)
    org = scenario.organizations[0]
    progress.process_fixture(work, jats_parser=host_parser)
    batch = progress.items(org, job)[0].batch_id
    assert batch is not None
    bundle = progress.associations.detail(org, batch)
    positions = {a.id: a.position for a in bundle.authors}
    addresses = {c.id: c.address.comparison_key for c in bundle.candidates}
    persisted = {
        (addresses[a.candidate_id], positions[a.author_id])
        for a in bundle.associations
        if a.author_id is not None
    }
    memory = OpenAccessOrchestrator(reference_year=2026).discover_and_extract(
        USHER.pmcid, target_roles="all"
    )
    expected = {
        (c.comparison_key, c.author_position)
        for c in memory.contacts_extracted
        if c.author_position is not None
    }
    assert persisted == expected and expected
    observation = stored(progress, org, job)
    assert observation["license_category"] == "cc-by"


# --------------------------------------------------------------- idempotency


def test_replayed_commit_returns_the_same_row_and_mutation_conflicts(scenario: Scenario) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    service = OaExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = service.binding(org, job, work.discovery_revision, PLOS.source_url)
        observed = host_parser(
            SETTINGS,
            registry.fixture_bytes(PLOS),
            JatsExpectation(
                requested_identifier=PLOS.identifier, content_digest=PLOS.content_digest
            ),
        )
        value = retain_jats(observed, PLOS, binding, excerpts)
        first = service.commit_jats(org, job, value)
        again = service.commit_jats(org, job, value)
        assert first["observation"] == again["observation"] and first["revision"] == 1
        changed = retain_jats(observed, PLOS, binding, excerpts=False)
        with pytest.raises(HTTPException) as conflict:
            service.commit_jats(org, job, changed)
        assert conflict.value.status_code == 409
    assert observation_count(scenario, job) == 1


@pytest.mark.parametrize(
    "field", ["organization", "job", "item", "generation", "policy_version", "discovery_revision"]
)
def test_binding_mismatch_is_refused(scenario: Scenario, field: str) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    service = OaExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = service.binding(org, job, work.discovery_revision, PLOS.source_url)
        observed = parse_jats_xml(registry.fixture_bytes(PLOS), PLOS.identifier)
        wrong = binding.model_copy(
            update={field: uuid4() if field in ("organization", "job", "item") else 999}
        )
        with pytest.raises(AuthorizationDenied):
            service.commit_jats(org, job, retain_jats(observed, PLOS, wrong, excerpts))
    assert observation_count(scenario, job) == 0


# ------------------------------------------------------------ policy and review


def test_no_excerpt_policy_strips_excerpts_and_never_accepts(scenario: Scenario) -> None:
    progress, job, work = running(scenario, excerpts=False)
    org = scenario.organizations[0]
    assert progress.process_fixture(work, jats_parser=host_parser) == "needs_review"
    batch = progress.items(org, job)[0].batch_id
    assert batch is not None
    bundle = progress.associations.detail(org, batch)
    assert all(not e.excerpt for e in bundle.evidence)
    association = next(a for a in bundle.associations if a.author_id is not None)
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
    results = Results(progress.database, progress.token, SETTINGS)
    assert results.contacts(org, Filters(job_id=job)).items == ()


def test_html_only_policy_cannot_plan_open_access(scenario: Scenario) -> None:
    with pytest.raises(AuthorizationDenied):
        planned(scenario, operation="fetch_html")


def test_unregistered_open_access_path_is_not_an_article(scenario: Scenario) -> None:
    from emailmonitor.discovery.planning import plan_input

    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/oa/PMC999999.xml"}
    assert plan_input(JobRequest.model_validate(body)).classification == "unsupported"
    body["input"] = {"type": "url", "url": PLOS.source_url}
    assert plan_input(JobRequest.model_validate(body)).reason == "open_access_fixture"


def test_suppressed_address_never_reaches_results(scenario: Scenario) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    Lifecycle(progress.database, progress.token, SETTINGS).suppress(
        org, SuppressionCreate(kind="contact", value=PLOS_ADDRESS, reason="privacy_request")
    )
    with pytest.raises((AuthorizationDenied, DBAPIError, HTTPException)):
        progress.process_fixture(work, jats_parser=host_parser)
    assert observation_count(scenario, job) == 0


def test_cancelled_work_never_reads_fixture_bytes(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    progress.control(org, job, progress.snapshot(org, job).revision, "cancel")

    def denied(document: object) -> bytes:
        raise AssertionError("Revoked work reached authored bytes")

    monkeypatch.setattr(registry, "fixture_bytes", denied)
    with bound(work.lease), pytest.raises(AuthorizationDenied):
        OaExtraction(progress.database, progress.token, SETTINGS).isolated_open_access(
            org, job, PLOS.source_url, work.discovery_revision, parser=host_parser
        )


# ---------------------------------------------------------- database guard


def _insert(
    progress: Progress, work: Work, org: UUID, job: UUID, document: dict[str, object]
) -> None:
    with bound(work.lease):
        with progress.extraction.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            c.execute(
                text("""INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,policy_version,discovery_revision,source_digest,observation)
VALUES(:org,:job,:url,:generation,:deletion,:policy,:discovery,:digest,
CAST(:document AS jsonb))"""),
                {
                    "org": org,
                    "job": job,
                    "url": document["url"],
                    "generation": work.lease.generation,
                    "deletion": work.lease.deletion_generation,
                    "policy": 1,
                    "discovery": work.discovery_revision,
                    "digest": document["content_digest"],
                    "document": json.dumps(document),
                },
            )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "canonical_url",
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML",
        ),
        ("content_digest", "0" * 64),
        ("acquisition_digest", "0" * 64),
        ("full_text_provider", "openalex"),
        ("isolation_profile", "in-process"),
        ("route", "html"),
        ("parser_version", "synthetic-html-v1"),
        ("requested_identifier", {"kind": "pmcid", "value": "PMC1234567"}),
        ("license_category", None),
        ("license_category", "cc-by-commercial"),
        ("license_category", {"class": "cc-by"}),
        ("reasons", ["deadline"]),
        ("keywords", ["x" * 301]),
        ("keywords", [{"text": "nested"}]),
        ("untrusted_extra_field", "free text kept outside any excerpt rule"),
    ],
)
def test_database_guard_refuses_altered_open_access_provenance(
    scenario: Scenario, field: str, value: object
) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    service = OaExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = service.binding(org, job, work.discovery_revision, PLOS.source_url)
    observed = parse_jats_xml(registry.fixture_bytes(PLOS), PLOS.identifier)
    document = retain_jats(observed, PLOS, binding, excerpts).model_dump(mode="json")
    document[field] = value
    with pytest.raises(DBAPIError, match=GUARD_REFUSAL):
        _insert(progress, work, org, job, document)
    assert observation_count(scenario, job) == 0


GUARD_REFUSAL = (
    r"JATS_OBSERVATION_PROVENANCE|ARTICLE_OBSERVATION_FENCE|ARTICLE_OBSERVATION_PROVENANCE"
)


def _retained_document(progress: Progress, work: Work, org: UUID, job: UUID) -> dict[str, object]:
    service = OaExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = service.binding(org, job, work.discovery_revision, PLOS.source_url)
    observed = parse_jats_xml(registry.fixture_bytes(PLOS), PLOS.identifier)
    return retain_jats(observed, PLOS, binding, excerpts).model_dump(mode="json")


@pytest.mark.parametrize(
    "mutation",
    ["unknown_author_position", "object_excerpt", "unsupported_with_authors", "binding_item"],
)
def test_database_guard_refuses_nested_tampering(scenario: Scenario, mutation: str) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    document = _retained_document(progress, work, org, job)
    candidates = document["candidates"]
    assert isinstance(candidates, list) and candidates
    if mutation == "unknown_author_position":
        candidates[0]["author_positions"] = [99]
    elif mutation == "object_excerpt":
        candidates[0]["evidence"]["excerpt"] = {"text": "retained outside the excerpt policy"}
    elif mutation == "unsupported_with_authors":
        document.update(status="unsupported", candidates=[])
    else:
        binding = document["binding"]
        assert isinstance(binding, dict)
        binding["item"] = str(uuid4())
    with pytest.raises(DBAPIError, match=GUARD_REFUSAL):
        _insert(progress, work, org, job, document)
    assert observation_count(scenario, job) == 0


def test_database_refuses_an_accepted_jats_association_without_review(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A buggy or compromised derive step cannot pre-accept an Open Access contact."""
    from emailmonitor.associations.mapping import map_observation as original

    def pre_accepted(*args: object, **kwargs: object) -> object:
        bundle = original(*args, **kwargs)  # type: ignore[arg-type]
        forged = tuple(
            a.model_copy(
                update={
                    "state": "accepted",
                    "evidence_strength": "explicit",
                    "reason": "explicit_observed_correspondence",
                }
            )
            if a.author_id is not None
            else a
            for a in bundle.associations
        )
        return bundle.model_copy(update={"associations": forged})

    monkeypatch.setattr("emailmonitor.associations.service.map_observation", pre_accepted)
    progress, job, work = running(scenario)
    with pytest.raises(DBAPIError, match="JATS_REVIEW_REQUIRED"):
        progress.process_fixture(work, jats_parser=host_parser)


def test_database_guard_accepts_the_unaltered_record(scenario: Scenario) -> None:
    progress, job, work = running(scenario)
    org = scenario.organizations[0]
    service = OaExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = service.binding(org, job, work.discovery_revision, PLOS.source_url)
    observed = parse_jats_xml(registry.fixture_bytes(PLOS), PLOS.identifier)
    _insert(
        progress,
        work,
        org,
        job,
        retain_jats(observed, PLOS, binding, excerpts).model_dump(mode="json"),
    )
    assert observation_count(scenario, job) == 1


# ------------------------------------------------------ isolated container


def test_actual_container_parses_open_access_jats(
    scenario: Scenario, require_isolation: None
) -> None:
    progress, job, work = running(scenario, USHER.source_url)
    assert progress.process_fixture(work) == "needs_review"
    observation = stored(progress, scenario.organizations[0], job)
    assert observation["isolation_profile"] == "network-none-parser-v1"
    assert observation["content_digest"] == USHER.content_digest


def test_reviewed_cc_by_contact_keeps_its_licence(scenario: Scenario) -> None:
    progress, job, work = running(scenario, USHER.source_url)
    org = scenario.organizations[0]
    progress.process_fixture(work, jats_parser=host_parser)
    batch = progress.items(org, job)[0].batch_id
    assert batch is not None
    bundle = progress.associations.detail(org, batch)
    association = next(a for a in bundle.associations if a.author_id is not None)
    progress.associations.review(
        org,
        batch,
        Review(
            association_id=association.id,
            expected_revision=association.revision,
            action="accept",
            evidence_ids=association.evidence_ids,
            reason="Inspected retained JATS author/address evidence",
        ),
    )
    contacts = Results(progress.database, progress.token, SETTINGS).contacts(
        org, Filters(job_id=job)
    )
    assert [c.license_category for c in contacts.items] == ["cc-by"]


def test_guard_key_and_licence_lists_match_the_python_model() -> None:
    """The SQL allow-lists in migration 0027 must stay identical to RetainedJats."""
    import re
    import typing
    from pathlib import Path

    from emailmonitor.sources.openaccess import LicenseCategory

    sql = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0027_open_access_fixture.sql"
    ).read_text()
    keys = re.search(
        r"jsonb_object_keys\(NEW\.observation\) k\) IS DISTINCT FROM ARRAY\[([^\]]+)\]", sql
    )
    assert keys is not None
    assert [k.strip("'") for k in keys.group(1).split(",")] == sorted(RetainedJats.model_fields)
    licences = re.search(r"license_category' NOT IN \(([^)]+)\)", sql)
    assert licences is not None
    assert [k.strip("'") for k in licences.group(1).split(",")] == list(
        typing.get_args(LicenseCategory)
    )
