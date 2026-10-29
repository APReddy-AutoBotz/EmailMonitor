"""Closed source-owned retained adapters; classification is not authority."""

from typing import Literal

from emailmonitor.extraction.pdf_fixture import DIGESTS as PDF_DIGESTS
from emailmonitor.jobs.models import JobRequest, URLInput
from emailmonitor.sources.provider_documents import ARTICLE_URLS

ORIGIN = "https://synthetic.publisher.example"
HTML_URLS = frozenset(
    f"{ORIGIN}/{name}" for name in ("article-a.html", "article-b.html", "no-contact.html")
)
PDF_URLS = frozenset(f"{ORIGIN}/{name}" for name in PDF_DIGESTS)
XML_URLS = frozenset({f"{ORIGIN}/article-xml.xml", *ARTICLE_URLS})
type Adapter = Literal["html", "pdf", "article_xml"]


def retained_adapter(request: JobRequest) -> Adapter | None:
    """Classify registered direct inputs only; no SQL, fetch or capability grant.

    XML/PDF classifications describe potential retained profiles. Their actual
    planning and database writes remain refused until their full authority and
    lifecycle path has been implemented and verified.
    """
    value = request.input
    if (
        request.reuse is None
        or not isinstance(value, URLInput)
        or value.source_id not in (None, "synthetic-publisher")
        or any(request.filters.model_dump(exclude_none=True).values())
    ):
        return None
    if value.url in HTML_URLS:
        return "html"
    if value.url in PDF_URLS and request.options.allow_pdf:
        return "pdf"
    if value.url in XML_URLS:
        return "article_xml"
    return None
