"""Source-owned classification is closed and never grants authority."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from emailmonitor.associations.reuse_adapters import retained_adapter, retained_plan
from emailmonitor.config import Settings
from emailmonitor.discovery.planning import plan_input
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from fastapi import HTTPException
from test_job_contracts import request_body


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://synthetic.publisher.example/article-a.html", "html"),
        ("https://synthetic.publisher.example/no-contact.html", "html"),
        ("https://synthetic.publisher.example/article-a.pdf", "pdf"),
        ("https://synthetic.publisher.example/article-xml.xml", "article_xml"),
        ("https://synthetic.publisher.example/provider-doi.xml", "article_xml"),
        ("https://synthetic.publisher.example/tooltip.html", None),
        ("https://synthetic.publisher.example/unregistered.pdf", None),
        ("https://other.example/article-a.pdf", None),
    ],
)
def test_registered_adapter_classification_is_not_an_authority_decision(
    url: str, expected: str | None
) -> None:
    request = JobRequest.model_validate(
        {
            **request_body(),
            "input": {"type": "url", "url": url},
            "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
        }
    )
    assert retained_adapter(request) == expected
    candidate = retained_plan(request)
    assert (candidate.adapter if candidate is not None else None) == expected
    if candidate is not None:
        assert candidate.article_url == url and candidate.source_id == "synthetic-publisher"
        assert candidate.fresh_since.isoformat() == "2000-01-01T00:00:00+00:00"
    if expected is None:
        assert plan_input(request).reason == "retained_reuse_unavailable"
    else:
        assert plan_input(request).reason == "retained_reuse_authored"


@pytest.mark.parametrize("failure", ["fresh", "other_source", "filter", "pdf_disabled"])
def test_classification_refuses_unselected_or_out_of_scope(failure: str) -> None:
    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/article-a.pdf"}
    body["reuse"] = {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"}
    if failure == "fresh":
        del body["reuse"]
    elif failure == "other_source":
        body["input"]["source_id"] = "other-source"  # type: ignore[index]
    elif failure == "filter":
        body["filters"] = {"journal": "Synthetic"}
    else:
        body["options"] = {**body["options"], "allow_pdf": False}  # type: ignore[dict-item]
    assert retained_adapter(JobRequest.model_validate(body)) is None


def test_reuse_refuses_an_explicit_empty_journal_filter() -> None:
    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/article-a.html"}
    body["reuse"] = {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"}
    body["filters"] = {"journal": ""}
    assert retained_adapter(JobRequest.model_validate(body)) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://synthetic.publisher.example/article-a.pdf",
        "https://synthetic.publisher.example/article-xml.xml",
        "https://synthetic.publisher.example/provider-doi.xml",
    ],
)
def test_public_creation_refuses_non_html_without_explicit_fixture_mode(url: str) -> None:
    request = JobRequest.model_validate(
        {
            **request_body(),
            "input": {"type": "url", "url": url},
            "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
        }
    )
    database, connection = MagicMock(), MagicMock()
    database.tenant.return_value.__enter__.return_value = (connection, MagicMock())
    with pytest.raises(HTTPException) as denied:
        Ledger(database, "synthetic", Settings(environment="test", fixture_mode=False)).create(
            UUID(int=1), request, "staged-reuse-key"
        )
    assert denied.value.status_code == 409
    connection.execute.assert_not_called()
