"""Pure bounded discovery checks against authored fixtures, no source sockets."""

import shlex
from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.discovery.fixture import fixture_bytes
from emailmonitor.discovery.planning import ORIGIN, plan_input
from emailmonitor.discovery.search import SearchPage, parse_search
from emailmonitor.discovery.state import DiscoveryState, advance
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.jobs.models import JobRequest
from pydantic import ValidationError
from test_job_contracts import request_body

SETTINGS = Settings(environment="test", fixture_mode=True)
ROOT = Path(__file__).resolve().parents[3]


def request(**input_changes: object) -> JobRequest:
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
        **input_changes,
    }
    return JobRequest.model_validate(body)


def page(number: int) -> SearchPage:
    return parse_search(
        SETTINGS, f"{ORIGIN}/search-page-{number}.html", fixture_bytes(f"search-page-{number}.html")
    )


def initial() -> DiscoveryState:
    return DiscoveryState(
        status="pending", reason="first_page", next_url=ORIGIN + "/search-page-1.html"
    )


def test_two_fixture_pages_four_unique_articles_and_truthful_denominator() -> None:
    first = advance(initial(), page(1), 2, 500)
    restored = DiscoveryState.model_validate_json(first.model_dump_json())
    final = advance(restored, page(2), 2, 500)
    assert final.status == "completed" and final.discovery_complete
    assert final.completeness == "pagination_exhausted"
    assert len(final.articles) == 4
    assert final.reported_total == final.raw_entries == 5
    assert final.duplicates == 1
    assert all("support" not in value for value in final.articles)
    assert final.api_fallback == "unavailable_not_attempted"
    assert final.extraction_implemented is False


def test_spelling_suggestion_requires_new_explicit_confirmed_request() -> None:
    original = request(original_query="Myocardial Infraction")
    plan = plan_input(original)
    assert plan.spelling_suggestion == "Myocardial Infarction"
    assert plan.effective_query == "Myocardial Infraction"
    assert plan.start_url is None
    with pytest.raises(ValidationError):
        request(original_query="Myocardial Infraction", effective_query="Myocardial Infarction")
    confirmed = plan_input(
        request(
            original_query="Myocardial Infraction",
            effective_query="Myocardial Infarction",
            query_change_confirmed=True,
        )
    )
    assert confirmed.original_query == "Myocardial Infraction"
    assert confirmed.start_url == ORIGIN + "/search-page-1.html"


@pytest.mark.parametrize(
    "url,kind",
    [
        (ORIGIN, "needs_refinement"),
        (ORIGIN + "/", "needs_refinement"),
        (ORIGIN + "/article-a.html", "article"),
        (ORIGIN + "/search-page-2.html", "search_results"),
        (ORIGIN + "/paper.pdf", "unsupported"),
        ("https://doi.org/10.1234/synthetic", "unsupported"),
        ("https://unknown.example/search", "unsupported"),
        (ORIGIN + "/search-page-1.html?q=secret", "unsupported"),
        ("http://synthetic.publisher.example/article-a.html", "unsupported"),
    ],
)
def test_url_preflight_never_domain_crawls(url: str, kind: str) -> None:
    body = request_body()
    body["input"] = {"type": "url", "url": url}
    assert plan_input(JobRequest.model_validate(body)).classification == kind


@pytest.mark.parametrize("change", [{"original_query": "other topic"}, {"source_id": "other"}])
def test_fixture_does_not_fabricate_arbitrary_topic_or_source_matches(
    change: dict[str, object],
) -> None:
    assert plan_input(request(**change)).start_url is None


def test_filters_are_not_silently_ignored() -> None:
    body = request_body()
    body["filters"] = {"journal": "Synthetic journal"}
    assert plan_input(JobRequest.model_validate(body)).reason == "fixture_filters_unavailable"


@pytest.mark.parametrize(
    "input_value",
    [
        {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        },
        {"type": "url", "url": ORIGIN + "/article-a.html"},
    ],
)
def test_explicit_reuse_does_not_silently_start_fresh_acquisition(
    input_value: dict[str, str],
) -> None:
    body = {
        **request_body(),
        "input": input_value,
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T13:00:00Z"},
    }
    plan = plan_input(JobRequest.model_validate(body))
    if input_value["type"] == "url":
        assert plan.classification == "article"
        assert plan.reason == "retained_reuse_authored" and plan.start_url == input_value["url"]
    else:
        assert plan.classification == "unsupported"
        assert plan.reason == "retained_reuse_unavailable" and plan.start_url is None


@pytest.mark.parametrize("date_type", ["published", "online", "issue"])
@pytest.mark.parametrize(
    "input_value",
    [
        {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        },
        {"type": "url", "url": ORIGIN + "/article-a.html"},
    ],
)
def test_explicit_date_filter_refuses_unsupported_fixture(
    date_type: str, input_value: dict[str, str]
) -> None:
    body = request_body()
    body["input"] = input_value
    body["filters"] = {
        "publication_date_type": date_type,
        "publication_from": "2026-01-15",
        "publication_to": "2026-01-15",
    }
    plan = plan_input(JobRequest.model_validate(body))
    assert plan.classification == "unsupported"
    assert plan.reason == "fixture_filters_unavailable" and plan.start_url is None


@pytest.mark.parametrize("pages,articles,reason", [(1, 500, "page_cap"), (2, 1, "article_cap")])
def test_caps_truthfully_stop_partial(pages: int, articles: int, reason: str) -> None:
    state = advance(initial(), page(1), pages, articles)
    assert state.status == "partial" and state.reason == reason
    assert state.next_url is None and state.completeness == "partial"


def test_repeated_cursor_and_changed_selector_are_partial() -> None:
    loop = page(1).model_copy(update={"next_url": ORIGIN + "/search-page-1.html"})
    assert advance(initial(), loop, 10, 500).reason == "repeated_cursor"
    changed = parse_search(
        SETTINGS,
        page(1).url,
        fixture_bytes("search-page-1.html").replace(b"search-results", b"changed-results"),
    )
    assert advance(initial(), changed, 10, 500).reason == "selectors_changed"


def test_no_new_results_and_changing_reported_total_are_partial() -> None:
    first = advance(initial(), page(1), 10, 500)
    second = page(2).model_copy(
        update={
            "exhausted": False,
            "next_url": ORIGIN + "/search-page-2.html",
            "articles": first.articles,
        }
    )
    assert advance(first, second, 10, 500).status == "partial"
    assert (
        advance(first, page(2).model_copy(update={"reported_total": 6}), 10, 500).reason
        == "reported_total_changed"
    )


@pytest.mark.parametrize(
    "replacement",
    [
        b"//outside.example/article-a.html",
        b"javascript:alert(1)",
        b"/login",
        b"article-a.html?token=x",
    ],
)
def test_untrusted_links_fail_closed(replacement: bytes) -> None:
    payload = fixture_bytes("search-page-1.html").replace(
        b'href="article-a.html"', b'href="' + replacement + b'"'
    )
    with pytest.raises(FetchDenied):
        parse_search(SETTINGS, page(1).url, payload)


@pytest.mark.parametrize("payload", [b"\xff", b"x" * 32769, b"<div>" * 70, b'<p x="a" x="b">'])
def test_encoding_depth_bytes_ambiguity_limits(payload: bytes) -> None:
    with pytest.raises(FetchDenied):
        parse_search(SETTINGS, ORIGIN + "/search-page-1.html", payload)


def test_scripts_templates_and_navigation_are_not_articles() -> None:
    payload = (
        b'<html><body><ol class="search-results"><li><a class="article-link" '
        b'href="article-a.html">one</a></li></ol><script>throw Error("inert")</script>'
        b'<template><a class="article-link" href="article-b.html">hidden</a></template>'
        b'<p data-pagination-exhausted="true"></p></body></html>'
    )
    result = parse_search(SETTINGS, ORIGIN + "/search-page-1.html", payload)
    assert result.articles == [ORIGIN + "/article-a.html"] and result.selector_valid


def test_production_parser_and_unknown_fixture_refuse() -> None:
    with pytest.raises(FetchDenied):
        parse_search(Settings(), ORIGIN + "/search-page-1.html", b"")
    with pytest.raises(FetchDenied):
        fixture_bytes("../article-a.html")


def test_replay_wrong_page_or_terminal_reducer_refuses() -> None:
    with pytest.raises(ValueError):
        advance(initial(), page(2), 2, 500)
    final = advance(advance(initial(), page(1), 2, 500), page(2), 2, 500)
    with pytest.raises(ValueError):
        advance(final, page(2), 2, 500)


def test_identifier_only_discovery_event_refuses_urls_and_wrong_shape() -> None:
    from uuid import uuid4

    from emailmonitor.discovery.broker import DiscoveryEvent

    body = {
        "organization_id": str(uuid4()),
        "job_id": str(uuid4()),
        "event_id": str(uuid4()),
        "generation": 1,
        "revision": 1,
    }
    assert DiscoveryEvent.model_validate(body).revision == 1
    with pytest.raises(ValidationError):
        DiscoveryEvent.model_validate({**body, "url": "https://outside.example"})
    with pytest.raises(ValidationError):
        DiscoveryEvent.model_validate({**body, "revision": True})


def test_repeated_page_fingerprint_stops_partial() -> None:
    first = advance(initial(), page(1), 10, 500)
    repeated = page(2).model_copy(update={"digest": page(1).digest})
    assert advance(first, repeated, 10, 500).reason == "repeated_page_content"


def test_discovery_schemas_examples_and_runtime_output_parity() -> None:
    import json

    import jsonschema
    from emailmonitor.discovery.broker import DiscoveryEvent

    for name, model in (
        ("discovery-event", DiscoveryEvent),
        ("discovery-checkpoint", DiscoveryState),
    ):
        schema = json.loads((ROOT / f"contracts/{name}.schema.json").read_text())
        instance = json.loads((ROOT / f"contracts/examples/{name}.json").read_text())
        jsonschema.validate(instance, schema)
        model.model_validate(instance)
    final = advance(advance(initial(), page(1), 2, 500), page(2), 2, 500)
    jsonschema.validate(
        final.model_dump(),
        json.loads((ROOT / "contracts/discovery-checkpoint.schema.json").read_text()),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": "completed", "discovery_complete": False, "next_url": None},
        {"status": "pending", "next_url": None},
        {"status": "partial", "next_url": ORIGIN + "/search-page-1.html"},
        {"articles": [ORIGIN + "/article-a.html", ORIGIN + "/article-a.html"]},
    ],
)
def test_checkpoint_schema_and_model_refuse_false_completeness(change: dict[str, object]) -> None:
    import json

    import jsonschema

    body = {**initial().model_dump(), **change}
    with pytest.raises(ValidationError):
        DiscoveryState.model_validate(body)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            body, json.loads((ROOT / "contracts/discovery-checkpoint.schema.json").read_text())
        )


def test_changed_article_selector_on_exhausted_page_is_partial() -> None:
    payload = fixture_bytes("search-page-2.html").replace(b"article-link", b"changed-link")
    changed = parse_search(SETTINGS, page(2).url, payload)
    assert not changed.selector_valid
    first = advance(initial(), page(1), 10, 500)
    assert advance(first, changed, 10, 500).reason == "selectors_changed"


@pytest.mark.parametrize("invalid", ["not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"])
def test_event_schema_matches_canonical_uuid_runtime_restriction(invalid: str) -> None:
    import json

    import jsonschema
    from emailmonitor.discovery.broker import DiscoveryEvent

    body = json.loads((ROOT / "contracts/examples/discovery-event.json").read_text())
    body["event_id"] = invalid
    with pytest.raises(ValidationError):
        DiscoveryEvent.model_validate(body)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            body, json.loads((ROOT / "contracts/discovery-event.schema.json").read_text())
        )


def test_exact_article_budget_stops_before_next_page() -> None:
    state = advance(initial(), page(1), 100, 2)
    assert state.status == "partial" and state.reason == "article_cap"
    assert len(state.articles) == 2 and state.next_url is None and not state.discovery_complete


def test_exact_budget_with_proven_exhaustion_can_complete() -> None:
    state = advance(advance(initial(), page(1), 100, 4), page(2), 100, 4)
    assert state.status == "completed" and state.discovery_complete
    assert len(state.articles) == 4 and state.completeness == "pagination_exhausted"


@pytest.mark.parametrize(
    "code,message,denied",
    [
        ("EM006", "DISCOVERY_POLICY_FENCE", True),
        ("42601", "syntax failure", False),
        ("P0001", "DISCOVERY_POLICY_FENCE", False),
        ("EM006", "DISCOVERY_JOB_FENCE", False),
    ],
)
def test_only_exact_policy_sql_fence_is_classified_as_denial(
    code: str, message: str, denied: bool
) -> None:
    import importlib

    from emailmonitor.discovery.service import policy_fence_denied
    from sqlalchemy.exc import DBAPIError

    original = importlib.import_module("pg8000.dbapi").ProgrammingError({"C": code, "M": message})
    error = DBAPIError(None, None, original, False)
    assert policy_fence_denied(error) is denied


def test_parser_build_context_includes_only_authored_copy_fixtures() -> None:
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    assert lines[0] == "**"
    assert [line for line in lines if line.startswith("!fixtures")] == [
        "!fixtures/",
        "!fixtures/html/",
        "!fixtures/html/search-page-1.html",
        "!fixtures/html/search-page-2.html",
        "!fixtures/html/article-a.html",
        "!fixtures/html/article-b.html",
        "!fixtures/html/tooltip.html",
        "!fixtures/html/no-contact.html",
        "!fixtures/pdf/",
        "!fixtures/pdf/article-a.pdf",
        "!fixtures/pdf/article-b.pdf",
        "!fixtures/pdf/wrapped.pdf",
        "!fixtures/pdf/ambiguous.pdf",
        "!fixtures/pdf/no-contact.pdf",
        "!fixtures/pdf/scanned.pdf",
        "!fixtures/pdf/encrypted.pdf",
        "!fixtures/pdf/page-cap.pdf",
        "!fixtures/pdf/corrupt.pdf",
        "!fixtures/xml/",
        "!fixtures/xml/sciencedirect-article.xml",
    ]
    # Docker matches both each path and its parents; admitting a parent alone
    # includes every descendant. Model the exact/** fixture rule subset with
    # ordered last-match semantics (moby/patternmatcher MatchesOrParentMatches).
    rules = [line for line in lines if line == "**" or "fixtures" in line]

    def included(path: str, patterns: list[str]) -> bool:
        excluded = False
        candidates = [path, *[str(p) for p in Path(path).parents if str(p) != "."]]
        for raw in patterns:
            admit = raw.startswith("!")
            pattern = raw.removeprefix("!").rstrip("/")
            assert "*" not in pattern or pattern == "**" or pattern.endswith("/**")
            match = any(
                pattern == "**"
                or candidate == pattern
                or (pattern.endswith("/**") and candidate.startswith(pattern[:-2]))
                for candidate in candidates
            )
            if match:
                excluded = not admit
        return not excluded

    expected = {
        "fixtures/html/search-page-1.html",
        "fixtures/html/search-page-2.html",
        "fixtures/html/article-a.html",
        "fixtures/html/article-b.html",
        "fixtures/html/tooltip.html",
        "fixtures/html/no-contact.html",
        "fixtures/pdf/article-a.pdf",
        "fixtures/pdf/article-b.pdf",
        "fixtures/pdf/wrapped.pdf",
        "fixtures/pdf/ambiguous.pdf",
        "fixtures/pdf/no-contact.pdf",
        "fixtures/pdf/scanned.pdf",
        "fixtures/pdf/encrypted.pdf",
        "fixtures/pdf/page-cap.pdf",
        "fixtures/pdf/corrupt.pdf",
        "fixtures/xml/sciencedirect-article.xml",
    }
    files = {str(p.relative_to(ROOT)) for p in (ROOT / "fixtures").rglob("*") if p.is_file()}
    assert {path for path in files if included(path, rules)} == expected
    for unexpected in (
        "fixtures/expected/new-secret.json",
        "fixtures/html/new-article.html",
        "fixtures/pdf/new.pdf",
        "fixtures/pdf/manifest.json",
        "fixtures/pdf/nested/article-a.pdf",
        "fixtures/html/nested/search-page-1.html",
        "fixtures/xml/unknown.xml",
        "fixtures/xml/manifest.json",
        "fixtures/xml/nested/sciencedirect-article.xml",
    ):
        assert not included(unexpected, rules)
    # Regression sensitivity: the prior parent admits must be shown to leak.
    prior_rules = [rule for rule in rules if rule not in {"fixtures/**", "fixtures/html/**"}]
    assert included("fixtures/expected/new-secret.json", prior_rules)
    assert included("fixtures/html/new-article.html", prior_rules)
    # Couple the deny-all context to every explicit parser fixture COPY source,
    # so a new Dockerfile input cannot silently be absent from the build context.
    dockerfile = (ROOT / "scripts/isolation/Dockerfile.parser").read_text()
    copied = {
        source
        for line in dockerfile.splitlines()
        if line.startswith("COPY ")
        for source in shlex.split(line)[1:-1]
        if source.startswith("fixtures/")
    }
    assert copied == expected
    assert all((ROOT / source).is_file() and included(source, rules) for source in copied)
    # Reproduce PR25's original missing-exception failure without invoking Docker.
    missing_xml = [rule for rule in rules if rule != "!fixtures/xml/sciencedirect-article.xml"]
    assert not included("fixtures/xml/sciencedirect-article.xml", missing_xml)
    broad_xml = [rule for rule in rules if rule != "fixtures/xml/**"]
    assert included("fixtures/xml/unknown.xml", broad_xml)
    assert (
        "COPY fixtures/html/search-page-1.html fixtures/html/search-page-2.html ./fixtures/"
        in dockerfile
    )
