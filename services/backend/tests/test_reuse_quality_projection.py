"""Owned fake transactions for original-bound reused XML/PDF projections."""

from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from emailmonitor.associations.quality import project_quality
from emailmonitor.associations.reuse_draft import independent_review_draft
from emailmonitor.associations.service import Associations
from emailmonitor.extraction.pdf_retained import PdfBinding, RetainedPdf, retain_pdf
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.organizations.database import AuthorizationDenied
from test_durable_jobs import SETTINGS
from test_pdf_extraction import parse as parse_pdf
from test_xml_pipeline import retained as retained_xml

ORG, SOURCE, TARGET, SOURCE_BATCH, TARGET_BATCH, ITEM = (UUID(int=i) for i in range(1, 7))


def setup(route: str, failure: str = "") -> tuple[MagicMock, MagicMock]:
    value: RetainedPdf | RetainedXml
    if route == "pdf":
        value = retain_pdf(
            parse_pdf("article-a.pdf"),
            PdfBinding(
                organization=ORG,
                job=SOURCE,
                item=ITEM,
                generation=1,
                deletion_generation=1,
                policy_version=1,
                discovery_revision=1,
            ),
            permit_excerpts=True,
        )
        digest = value.content_digest
    else:
        xml = retained_xml()
        value = xml.model_copy(update={"binding": xml.binding.model_copy(update={"item": ITEM})})
        digest = value.acquisition_digest
    document = value.model_dump(mode="json")
    target = {
        "observation": document,
        "job_id": TARGET,
        "generation": 1,
        "policy_version": 1,
        "deletion_generation": 1,
        "source_digest": digest,
        "article_url": value.url,
        "reused_from_job": SOURCE,
        "reused_source_revision": 1,
        "reused_source_batch": SOURCE_BATCH,
    }
    origin = {
        "job_id": SOURCE,
        "generation": 1,
        "policy_version": 1,
        "deletion_generation": 1,
        "revision": 1,
        "source_digest": digest,
        "observation": document,
        "discovery_revision": 1,
        "source_parent_job": None,
    }
    bundle = independent_review_draft(SETTINGS, ORG, ORG, SOURCE, TARGET, value)
    service, connection = MagicMock(), MagicMock()
    service._lock = MagicMock()
    service.discovery._tenant.return_value = nullcontext((connection, object()))
    service._bundle.return_value = bundle
    source_reads = 0

    def execute(statement: object, *_: object) -> MagicMock:
        nonlocal source_reads
        result = MagicMock()
        sql = str(statement)
        if "SELECT source.observation" in sql:
            result.mappings.return_value.first.return_value = target.copy()
        elif "SELECT a.organization_id" in sql:
            source_reads += 1
            row = origin.copy()
            if failure == "wrong_job":
                row["job_id"] = TARGET
            if failure == "chain":
                row["source_parent_job"] = UUID(int=99)
            if failure == "wrong_discovery":
                row["discovery_revision"] = 2
            if failure == "wrong_digest" or (failure == "changed_origin" and source_reads > 1):
                row["source_digest"] = "0" * 64
            result.mappings.return_value.first.return_value = row
        elif "SELECT id FROM emailmonitor.execution_items" in sql:
            result.scalar_one_or_none.return_value = None if failure == "missing_item" else ITEM
        else:
            raise AssertionError("Unexpected source-view query")
        return result

    connection.execute.side_effect = execute
    return service, connection


@pytest.mark.parametrize("route", ["xml", "pdf"])
def test_reused_quality_keeps_original_parser_binding(route: str) -> None:
    service, _ = setup(route)
    quality = Associations._observation_view(service, ORG, TARGET_BATCH, project_quality)
    assert quality.observation_route == ("article_xml" if route == "xml" else "pdf")
    assert quality.batch_id == TARGET_BATCH
    assert [call.args[2] for call in service._lock.call_args_list] == [
        SOURCE_BATCH,
        TARGET_BATCH,
        SOURCE_BATCH,
    ]


@pytest.mark.parametrize("route", ["xml", "pdf"])
@pytest.mark.parametrize(
    "failure",
    ["wrong_job", "wrong_digest", "changed_origin", "missing_item", "chain", "wrong_discovery"],
)
def test_reused_quality_refuses_unproved_original(route: str, failure: str) -> None:
    service, _ = setup(route, failure)
    with pytest.raises(AuthorizationDenied):
        Associations._observation_view(service, ORG, TARGET_BATCH, project_quality)
