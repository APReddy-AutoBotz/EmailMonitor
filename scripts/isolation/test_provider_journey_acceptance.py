"""Actual same-data keyword→protected HTTPS→isolated XML→SQL→review/export proof.

A third sequential instance of the existing topology preserves all original guest,
network, callback, pipe and process ceilings. No live publisher is contacted.
"""

import io
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID
from zipfile import ZipFile

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.fetching.sciencedirect import AcquiredResponse, ProviderBoundary
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.provider import ProviderJourney
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from emailmonitor.sources import provider_documents as catalog
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_progress_tenant import claim
from test_provider_journey_tenant import planned_provider
from test_results_tenant import ready
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario
from test_transport_acceptance import configure, snapshot
from test_transport_acceptance import topology as topology
from test_xml_pipeline_tenant import mutate_authority
from transport_provider import ProviderProxy
from transport_topology import Topology
from xml_image_evidence import require_packaged_image


class ControlledDispatch:
    def __init__(
        self,
        proxy: ProviderProxy,
        family: int = 4,
        after_response: Callable[[], None] = lambda: None,
    ):
        self.proxy, self.family, self.after_response = proxy, family, after_response

    def acquire(self, boundary: ProviderBoundary, *, resources: HopResources) -> AcquiredResponse:
        return self.proxy.acquire(
            boundary, resources=resources, family=self.family, after_finish=self.after_response
        )


@pytest.mark.parametrize("family", [4, 6])
def test_actual_keyword_to_same_database_review_and_exports(
    topology: Topology,
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    family: int,
) -> None:
    from emailmonitor.parsing import xml_channel

    configure(topology)
    profiles: list[Mapping[str, object]] = []
    original_verify = xml_channel.verify_profile

    def verified(metadata: Mapping[str, object]) -> None:
        original_verify(metadata)
        require_packaged_image(metadata)
        profiles.append(metadata)

    monkeypatch.setattr(xml_channel, "verify_profile", verified)
    progress, job = planned_provider(scenario)
    org = scenario.organizations[0]

    def reserved_until() -> datetime:
        # Current-tenant admission timestamp, not variable post-DNS/TLS arrival time.
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
            value: object = c.execute(
                text(
                    "SELECT ready_at FROM emailmonitor.tenant_source_buckets "
                    "WHERE organization_id=:org AND source_id=:source"
                ),
                {"org": org, "source": catalog.SOURCE},
            ).scalar_one()
            assert isinstance(value, datetime)
            return value

    reservations: list[datetime] = []
    progress.start(org, job, progress.snapshot(org, job).revision)
    proxy = ProviderProxy(topology.processes["gateway"])
    journey = ProviderJourney(progress, ControlledDispatch(proxy, family))
    search = claim(progress, org, job)
    assert journey.process(search) == "succeeded"
    reservations.append(reserved_until())
    discovered = progress.snapshot(org, job)
    assert discovered.unique_articles == 2 and discovered.duplicates == 1
    assert discovered.discovery_complete and discovered.discovery_pages == 1
    first = claim(progress, org, job)

    def crash() -> None:
        raise RuntimeError("Owned synthetic crash after observation commit")

    with pytest.raises(RuntimeError, match="synthetic crash"):
        journey.process(first, after_observation=crash)
    reservations.append(reserved_until())
    assert len(progress.extraction.read(org, job)) == 1
    assert len(snapshot(topology)["calls"]) == 2
    # A fresh service and new durable lease recover the exact persisted output.
    assert progress.finish(first, failure="worker_failure") == "retry_wait"
    recovered_progress = Progress(progress.database, progress.token, SETTINGS)
    event = next(
        r
        for r in recovered_progress.pending(org)
        if r["job_id"] == job and r["item_id"] == first.lease.item
    )
    recovered = recovered_progress.claim(org, job, first.lease.item, UUID(str(event["event_id"])))
    assert recovered is not None and recovered.lease.token != first.lease.token
    recovered_journey = ProviderJourney(recovered_progress, ControlledDispatch(proxy, family))
    assert recovered_journey.process(recovered) == "needs_review"
    assert len(snapshot(topology)["calls"]) == 2 and len(profiles) == 1
    assert reserved_until() == reservations[-1]
    second = claim(progress, org, job)
    assert journey.process(second) == "needs_review"
    reservations.append(reserved_until())
    final = progress.snapshot(org, job)
    assert final.state == "completed" and final.counts.by_outcome == {"needs_review": 2}
    assert len(profiles) == 2
    observations = progress.extraction.read(org, job)
    assert len(observations) == 2
    retained = [RetainedXml.model_validate_json(json.dumps(r["observation"])) for r in observations]
    assert {r.requested_identifier.kind for r in retained} == {"doi", "pii"}
    assert all(r.provider is not None and r.provider.requested_view == "FULL" for r in retained)
    results = Results(progress.database, progress.token, SETTINGS)
    assert results.contacts(org, Filters(job_id=job)).items == ()
    for item in progress.items(org, job):
        if item.work_kind != "article":
            continue
        assert item.batch_id is not None
        bundle = progress.associations.detail(org, item.batch_id)
        assert {a.state for a in bundle.associations} == {"needs_review"}
        target = (
            "Second@example.org" if bundle.source_url == catalog.DOI_URL else "beta@example.org"
        )
        candidate = next(c for c in bundle.candidates if c.address.raw_address == target)
        association = next(a for a in bundle.associations if a.candidate_id == candidate.id)
        evidence = results.evidence(org, item.batch_id, association.evidence_ids[0])
        expected_digest = next(r.content_digest for r in retained if r.url == bundle.source_url)
        assert (
            evidence.content_digest == expected_digest and evidence.source_url == bundle.source_url
        )
        progress.associations.review(
            org,
            item.batch_id,
            Review(
                association_id=association.id,
                expected_revision=association.revision,
                action="accept",
                evidence_ids=association.evidence_ids,
                reason="Inspected the retained controlled XML author and address evidence",
            ),
        )
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == 2
    assert {c.source_url for c in contacts} == catalog.ARTICLE_URLS
    assert all(
        c.technical_status == "not_checked" and c.outreach_eligibility == "not_assessed"
        for c in contacts
    )
    exports = []
    for format in ("csv", "xlsx"):
        export = ready(results, org, job, format=format)
        artifact = results.download(org, export)
        with ZipFile(io.BytesIO(artifact.body)) as archive:
            joined = b"\n".join(archive.read(name) for name in archive.namelist())
            assert b"Second@example.org" in joined and b"beta@example.org" in joined
            assert all(
                str(c.batch_id).encode() in joined and c.source_url.encode() in joined
                for c in contacts
            )
        exports.append(export)
    with scenario.client() as client:
        scenario.login(client, "owner_b")
        other = Progress(progress.database, str(client.cookies[COOKIE]), SETTINGS)
        for target_org in (org, scenario.organizations[1]):
            with pytest.raises(AuthorizationDenied):
                other.extraction.read(target_org, job)
        other_results = Results(other.database, other.token, SETTINGS)
        for export in exports:
            with pytest.raises(AuthorizationDenied):
                other_results.download(org, export)
    assert progress.claim(org, job, recovered.lease.item, UUID(str(event["event_id"]))) is None
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
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
        tickets = c.execute(
            text(
                "SELECT operation,state FROM emailmonitor.source_resource_requests "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": job},
        ).all()
        assert len(tickets) == 3 and all(t.state == "finished" for t in tickets)
        assert {t.operation for t in tickets} == {"search", "fetch_xml"}
        operational: dict[str, Any] = c.execute(
            text("SELECT emailmonitor.administration_usage(:org)"), {"org": org}
        ).scalar_one()
        assert operational["source_resource_attempts"] == 3
        assert operational["active_units"].get("http", 0) == 0
    calls = snapshot(topology)["calls"]
    assert len(calls) == 3 and calls[0]["method"] == "PUT"
    assert json.loads(calls[0]["body"])["qs"] == catalog.QUERY
    assert all(c["method"] == "GET" and c["path"].endswith("?view=FULL") for c in calls[1:])
    assert len({c["path"] for c in calls[1:]}) == 2
    assert all(
        (right - left).total_seconds() >= 5.0
        for left, right in zip(reservations, reservations[1:], strict=False)
    )
    mutate_authority(scenario, progress, job, "retention")
    for export in exports:
        with pytest.raises((AuthorizationDenied, HTTPException)):
            results.download(org, export)
    print(
        json.dumps(
            {
                "proof": "PROVIDER_KEYWORD_HTTPS_ISOLATED_SQL_REVIEW_EXPORT",
                "family": family,
                "method": "PUT",
                "view": "FULL",
                "articles": 2,
                "duplicate_entries": 1,
                "parser_image_ids": sorted({str(p["Image"]) for p in profiles}),
                "actual_parser_profiles": 2,
                "recovery_refetched": False,
                "effects": 2,
                "sql_resource_tickets": 3,
                "tenant_b": "denied",
                "retention": "denied",
                "formats": ["csv", "xlsx"],
                "digests": [r.content_digest for r in retained],
            }
        ),
        flush=True,
    )


def test_actual_keyword_cap_stops_before_second_article(
    topology: Topology, scenario: Scenario
) -> None:
    configure(topology)
    progress, job = planned_provider(scenario, max_articles=1)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    journey = ProviderJourney(
        progress, ControlledDispatch(ProviderProxy(topology.processes["gateway"]))
    )
    assert journey.process(claim(progress, org, job)) == "succeeded"
    discovery = progress.snapshot(org, job)
    assert discovery.unique_articles == 1 and discovery.discovery_stop_reason == "article_cap"
    assert journey.process(claim(progress, org, job)) == "needs_review"
    final = progress.snapshot(org, job)
    assert final.state == "completed_partial" and final.counts.terminal == 1
    assert len(progress.extraction.read(org, job)) == 1 and not progress.pending(org)
    calls = snapshot(topology)["calls"]
    assert len(calls) == 2 and calls[0]["method"] == "PUT"
    assert calls[1]["method"] == "GET" and calls[1]["path"].endswith("?view=FULL")


@pytest.mark.parametrize(
    "stage,kind",
    [
        ("response", "cancel"),
        ("response", "revoked_policy"),
        ("parse", "delete"),
        ("parse", "retention"),
        ("parse", "suppression"),
        ("parse", "lost_lease"),
        ("before", "revoked_session"),
    ],
)
def test_actual_provider_acquisition_never_survives_authority_changes(
    topology: Topology,
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    kind: str,
) -> None:
    from emailmonitor.extraction import provider_xml

    configure(topology)
    progress, job = planned_provider(scenario, url=catalog.DOI_URL)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)

    def change() -> None:
        mutate_authority(scenario, progress, job, kind)

    if stage == "parse":
        from emailmonitor.parsing.xml_channel import parse_isolated

        original = parse_isolated

        def changed(*args: object, **kwargs: object) -> object:
            result = original(*args, **kwargs)  # type: ignore[arg-type]
            change()
            return result

        monkeypatch.setattr(provider_xml, "parse_isolated", changed)
    if stage == "before":
        change()
    dispatch = ControlledDispatch(
        ProviderProxy(topology.processes["gateway"]),
        after_response=change if stage == "response" else lambda: None,
    )
    with pytest.raises((FetchDenied, AuthorizationDenied, DBAPIError, HTTPException)):
        ProviderJourney(progress, dispatch).process(work)
    assert len(snapshot(topology)["calls"]) == (0 if stage == "before" else 1)
    admin = create_engine(scenario.admin_url)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_effects "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()
