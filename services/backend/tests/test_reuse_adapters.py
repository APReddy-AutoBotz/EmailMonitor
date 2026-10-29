"""Source-owned classification is closed and does not enable adapters."""

import pytest
from emailmonitor.associations.reuse_adapters import retained_adapter
from emailmonitor.discovery.planning import plan_input
from emailmonitor.jobs.models import JobRequest
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
def test_registered_adapter_classification_never_enables_bound_routes(
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
    if expected != "html":
        assert plan_input(request).reason == "retained_reuse_unavailable"


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
