"""Synthetic offline request descriptions; no Elsevier call or contact data."""

import json
import socket

import pytest
from emailmonitor.jobs.models import Filters
from emailmonitor.sources.sciencedirect_filter_plan import (
    DocumentedSearchCapabilities,
    DocumentedSearchRequest,
    ProviderFilterRefused,
)
from pydantic import ValidationError


def test_provider_native_terms_are_preserved_without_network_or_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network is unavailable in this test")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "socket", no_network)
    query = DocumentedSearchRequest(
        query='"synthetic" AND topic',
        provider_publication_year_query="2020-2024",
        provider_title_search="Synthetic Journal OR Synthetic Book",
        offset=50,
        show=25,
    )
    plan = query.plan()
    assert plan.request.method == "PUT"
    assert plan.request.origin == "https://api.elsevier.com"
    assert plan.request.path == "/content/search/sciencedirect"
    assert plan.request.execution_enabled is False
    assert json.loads(plan.request.body) == {
        "qs": '"synthetic" AND topic',
        "display": {"offset": 50, "show": 25, "sortBy": "relevance"},
        "date": "2020-2024",
        "pub": "Synthetic Journal OR Synthetic Book",
    }
    assert plan.result_status == "unknown_may_be_truncated"
    assert plan.capabilities.year_range_endpoint_inclusivity == "unspecified"
    assert plan.capabilities.title_matching == "unspecified"
    assert plan.capabilities.title_scope == "journal_or_book"
    assert plan.capabilities.complete_search_guarantee is False


def test_provider_defaults_and_single_year_do_not_add_implicit_filters() -> None:
    plan = DocumentedSearchRequest(query="synthetic", provider_publication_year_query="2024").plan()
    body = json.loads(plan.request.body)
    assert body == {
        "qs": "synthetic",
        "display": {"offset": 0, "show": 25, "sortBy": "relevance"},
        "date": "2024",
    }
    assert "loadedAfter" not in body and "filters" not in body and "pub" not in body
    assert DocumentedSearchCapabilities().source_result_limit == 6000


@pytest.mark.parametrize(
    "product_filters",
    [
        {"publication_date_type": "published", "publication_from": "2024-01-01"},
        {"publication_date_type": "online", "publication_to": "2024-12-31"},
        {"journal": "Synthetic Journal"},
        {"journal": ""},
        {"article_types": ["review"]},
    ],
)
def test_product_semantics_are_never_approximated(product_filters: dict[str, object]) -> None:
    request = DocumentedSearchRequest(
        query="synthetic",
        provider_publication_year_query="2024",
        provider_title_search="Synthetic Journal",
        product_filters=Filters.model_validate(product_filters),
    )
    with pytest.raises(ProviderFilterRefused, match="^product_filters_unsupported$"):
        request.plan()


def test_product_filters_are_rechecked_when_nested_value_changes() -> None:
    request = DocumentedSearchRequest(query="synthetic")
    request.product_filters.journal = ""
    with pytest.raises(ProviderFilterRefused, match="^product_filters_unsupported$"):
        request.plan()


@pytest.mark.parametrize(
    "change",
    [
        {"provider_publication_year_query": "2024-01-01"},
        {"provider_publication_year_query": "2025-2024"},
        {"provider_publication_year_query": "2024 - 2025"},
        {"provider_title_search": ""},
        {"provider_title_search": " "},
        {"provider_title_search": "x" * 251},
        {"provider_title_search": "\ud800"},
        {"offset": 5991, "show": 10},
        {"offset": 6000},
        {"offset": True},
        {"show": 200},
        {"loadedAfter": "2024-01-01T00:00:00Z"},
        {"article_type": "review"},
        {"api_key": "synthetic-key"},
    ],
)
def test_non_contract_inputs_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DocumentedSearchRequest.model_validate({"query": "synthetic", **change})


def test_conservative_last_page_cannot_be_mistaken_for_completeness() -> None:
    plan = DocumentedSearchRequest(query="synthetic", offset=5990, show=10).plan()
    assert json.loads(plan.request.body)["display"]["offset"] == 5990
    assert plan.result_status == "unknown_may_be_truncated"
    assert plan.capabilities.complete_search_guarantee is False
    with pytest.raises(ValidationError):
        DocumentedSearchCapabilities(live_execution=True)  # type: ignore[arg-type]
