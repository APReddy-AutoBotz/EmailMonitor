"""Pure connector-owned input classification; never resolves or fetches a URL."""

from dataclasses import dataclass

from emailmonitor.fetching.fixture import HOSTS
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.jobs.models import JobRequest, KeywordInput
from emailmonitor.sources.filter_capabilities import REGISTERED_FIXTURE_FILTERS, assess_filters

ORIGIN = "https://synthetic.publisher.example"
SEARCH_PATHS = frozenset({"/search-page-1.html", "/search-page-2.html"})
ARTICLE_PATHS = frozenset(
    {"/article-a.html", "/article-b.html", "/tooltip.html", "/no-contact.html"}
)
DEFAULT_TOPIC = "Myocardial Infarction"


@dataclass(frozen=True)
class InputPlan:
    classification: str
    reason: str
    start_url: str | None = None
    original_query: str | None = None
    effective_query: str | None = None
    spelling_suggestion: str | None = None
    api_fallback: str = "unavailable_not_attempted"


def staged_bound_reuse_input(request: JobRequest) -> InputPlan:
    """Describe a registered XML/PDF retained input without enabling it."""
    from emailmonitor.associations.reuse_adapters import retained_plan

    candidate = retained_plan(request)
    if candidate is not None and candidate.adapter in {"pdf", "article_xml"}:
        return InputPlan("article", "retained_reuse_staged", candidate.article_url)
    return InputPlan("unsupported", "retained_reuse_unavailable")


def plan_input(request: JobRequest) -> InputPlan:
    from emailmonitor.sources import provider_documents as provider

    value = request.input
    if request.reuse is not None:
        from emailmonitor.associations.reuse_adapters import retained_plan

        candidate = retained_plan(request)
        if candidate is not None:
            return InputPlan("article", "retained_reuse_authored", candidate.article_url)
        return InputPlan("unsupported", "retained_reuse_unavailable")
    if assess_filters(request.filters, REGISTERED_FIXTURE_FILTERS) != "none_requested":
        return InputPlan("unsupported", "fixture_filters_unavailable")
    if isinstance(value, KeywordInput):
        effective = value.effective_query or value.original_query
        suggestion = DEFAULT_TOPIC if value.original_query == "Myocardial Infraction" else None
        if value.source_id != "synthetic-publisher":
            return InputPlan("unsupported", "source_onboarding_required")
        if effective == provider.QUERY:
            return InputPlan(
                "search_results",
                "controlled_provider_fixture",
                provider.SEARCH_URL,
                value.original_query,
                effective,
                suggestion,
            )
        # The immutable fixture search index supports exactly this topic. Never
        # misrepresent arbitrary keywords as having the same fixture results.
        if effective != DEFAULT_TOPIC:
            return InputPlan(
                "needs_refinement",
                "fixture_topic_unavailable",
                None,
                value.original_query,
                effective,
                suggestion,
            )
        return InputPlan(
            "search_results",
            "supported_fixture",
            ORIGIN + "/search-page-1.html",
            value.original_query,
            effective,
            suggestion,
        )
    if value.source_id not in (None, "synthetic-publisher"):
        return InputPlan("unsupported", "source_onboarding_required")
    try:
        url = classify_url(value.url, HOSTS)
    except FetchDenied:
        return InputPlan("unsupported", "unsafe_or_unonboarded_url")
    if url.normalized in provider.URLS:
        return InputPlan(
            "search_results" if url.normalized == provider.SEARCH_URL else "article",
            "controlled_provider_fixture",
            url.normalized,
        )
    if url.path == "/":
        return InputPlan("needs_refinement", "homepage_requires_keyword_or_scoped_url")
    if url.path in SEARCH_PATHS:
        return InputPlan("search_results", "supported_fixture", url.normalized)
    if url.path in ARTICLE_PATHS or url.path == "/article-xml.xml":
        return InputPlan("article", "supported_fixture", url.normalized)
    from emailmonitor.extraction.pdf_fixture import DIGESTS

    if url.normalized in {ORIGIN + "/" + name for name in DIGESTS}:
        if not request.options.allow_pdf:
            return InputPlan("unsupported", "pdf_disabled")
        return InputPlan("article", "authored_local_pdf", url.normalized)
    if url.path.lower().endswith(".pdf"):
        return InputPlan("unsupported", "fixture_pdf_unavailable")
    return InputPlan("unsupported", "fixture_route_unavailable")
