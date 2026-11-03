"""Actual owned PDF capability plus ordinary tenant SQL; no installed-image claim."""

import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction.pdf import PdfObservation
from emailmonitor.fetching.provider_proxy import GatewayPipe
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.parsing.pdf_protocol import PdfExpectation
from emailmonitor.runtime.controlled_channel import ControlledChannel, FramedSocket
from emailmonitor.runtime.controlled_launcher import serve_request
from sqlalchemy import create_engine, text
from test_pdf_pipeline_tenant import assert_durable_journey, planned_pdf
from test_progress_tenant import claim
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario
from test_xml_pipeline_tenant import mutate_authority


@contextmanager
def owned_parser() -> Iterator[ControlledChannel]:
    image = os.environ.get("EM_TEST_PDF_IMAGE_ID") or os.environ.get("EM_EXPECTED_XML_IMAGE_ID", "")
    if not image:
        if os.environ.get("EM_REQUIRE_XML_ISOLATION") == "true":
            pytest.fail("Required pinned PDF parser image unavailable")
        pytest.skip("Actual pinned PDF parser image required")
    left, right = socket.socketpair()
    client, server = ControlledChannel(left), FramedSocket(right)
    gateway = Mock(spec=GatewayPipe)
    errors: list[str] = []

    def host() -> None:
        try:
            serve_request(server, gateway, image)
        except Exception as error:
            errors.append(type(error).__name__)
            server.close()

    thread = threading.Thread(target=host)
    thread.start()
    try:
        yield client
        thread.join(2)
        assert not thread.is_alive() and errors == [] and gateway.mock_calls == []
    finally:
        client.close()
        server.close()
        thread.join(2)
        assert not thread.is_alive()


def test_actual_controlled_pdf_durable_replay_review_export(scenario: Scenario) -> None:
    with owned_parser() as client:
        assert_durable_journey(scenario, "article-a.pdf", sql_only=False, parser=client.parse_pdf)


def test_actual_controlled_pdf_cancel_after_parse_cannot_commit(scenario: Scenario) -> None:
    progress, job = planned_pdf(scenario, "article-a.pdf")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    with owned_parser() as client:

        def cancel(settings: Settings, data: bytes, *, expected: PdfExpectation) -> PdfObservation:
            observed = client.parse_pdf(settings, data, expected=expected)
            mutate_authority(scenario, progress, job, "cancel")
            return observed

        with pytest.raises(AuthorizationDenied):
            progress.process_fixture(work, pdf_parser=cancel)
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
    finally:
        admin.dispose()
