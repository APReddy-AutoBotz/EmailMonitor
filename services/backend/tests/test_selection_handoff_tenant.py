"""Actual SQL membership for the accepted-results UI handoff; no new authority."""

import csv
import io
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from emailmonitor.lifecycle.models import DeletionRequest
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.results.models import ExportInput
from test_durable_jobs import SETTINGS
from test_results_tenant import lease
from test_retained_paper_identity_tenant import DOI, pair
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def rows(body: bytes, format: str, outcomes: bool) -> list[list[str]]:
    with ZipFile(io.BytesIO(body)) as archive:
        if format == "csv":
            path = "article-outcomes.csv" if outcomes else "contacts.csv"
            return list(csv.reader(io.StringIO(archive.read(path).decode())))
        path = "xl/worksheets/sheet2.xml" if outcomes else "xl/worksheets/sheet1.xml"
        root = ET.fromstring(archive.read(path))
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        return [
            ["".join(cell.itertext()) for cell in row.findall("s:c", ns)]
            for row in root.findall("s:sheetData/s:row", ns)
        ]


@pytest.mark.parametrize("format", ["csv", "xlsx"])
@pytest.mark.parametrize(
    "presence", ["observed_candidate", "completed_without_candidate", "unresolved"]
)
def test_actual_accepted_handoff_preview_and_artifact_membership(
    scenario: Scenario, format: str, presence: str
) -> None:
    progress, results, first, second = pair(scenario)
    org = scenario.organizations[0]
    item = results.outcomes(org, first).items[0]
    # Same whitelisted selectors as UI; acceptance is never copied from Review.
    request = ExportInput.model_validate(
        {
            "job_id": str(first),
            "item_id": str(item.item_id),
            "paper_doi": DOI,
            "query": "alex.chen",
            "author_target": "corresponding",
            "article_outcome_presence": presence,
            "include_unresolved": False,
            "include_article_outcomes": True,
            "format": format,
            "purpose": "academic_contact_research",
        }
    )
    contacts = results.contacts(org, request.filters()).items
    assert len(contacts) == 1 and contacts[0].state == "accepted"
    preview = results.preview(org, request)
    assert preview.contacts == 1
    assert preview.article_outcomes == (1 if presence == "observed_candidate" else 0)
    key = str(uuid4())
    state = results.create(org, request, key)
    assert results.create(org, request, key).id == state.id
    with pytest.raises(RevisionConflict):
        results.create(org, request.model_copy(update={"query": "different"}), key)
    work = lease(results, org, state.id)
    assert work.snapshot.contacts == contacts
    assert {row.job_id for row in work.snapshot.contacts} == {first}
    assert second not in {row.job_id for row in work.snapshot.article_outcomes}
    assert results.process(work)
    artifact = results.download(org, state.id).body
    contact_rows = rows(artifact, format, False)
    outcome_rows = rows(artifact, format, True)
    assert len(contact_rows) - 1 == preview.contacts
    assert len(outcome_rows) - 1 == preview.article_outcomes
    assert str(first) in contact_rows[1] and str(second) not in contact_rows[1]
    assert contacts[0].raw_address in contact_rows[1]
    with pytest.raises(AuthorizationDenied):
        results.preview(scenario.organizations[1], request)
    Lifecycle(progress.database, progress.token, SETTINGS).stage(
        org, DeletionRequest(job_id=first, reason="privacy_request")
    )
    with pytest.raises(AuthorizationDenied):
        results.download(org, state.id)
    # Existing-key replay is metadata-only; it must not grant access or create work.
    replay = results.create(org, request, key)
    assert replay.id == state.id and not replay.download_available
    with pytest.raises(AuthorizationDenied):
        results.download(org, replay.id)
    with pytest.raises(AuthorizationDenied):
        results.create(org, request, str(uuid4()))
