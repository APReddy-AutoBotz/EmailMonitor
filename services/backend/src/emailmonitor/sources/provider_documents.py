"""Server-owned controlled source bindings; never a permission for a live provider.

The durable source URL, identifier-derived API URL, and controlled acquisition
provenance are different identities. Only catalog-owned mappings may join them.
"""

import json
from typing import Literal

from pydantic import Field, model_validator

from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.fetching.sciencedirect import ProviderRequest
from emailmonitor.sources.sciencedirect import ArticleIdentifier, Contract, SearchArticle

SOURCE = "synthetic-publisher"
ORIGIN = "https://synthetic.publisher.example"
QUERY = "Controlled provider journey"
SEARCH_URL = ORIGIN + "/provider-search-0.json"
DOI_URL = ORIGIN + "/provider-doi.xml"
PII_URL = ORIGIN + "/provider-pii.xml"
ARTICLE_URLS = frozenset({DOI_URL, PII_URL})
URLS = ARTICLE_URLS | {SEARCH_URL}


class ProviderDocument(Contract):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    source_url: str = Field(max_length=2048)
    identifier: ArticleIdentifier
    aliases: tuple[ArticleIdentifier, ...] = Field(default=(), max_length=4)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_profile: Literal["article_retrieval_response", "xocs_document"]
    acquisition_mode: Literal["controlled_fixture"] = "controlled_fixture"

    @model_validator(mode="after")
    def registered_shape(self) -> "ProviderDocument":
        if (
            self.source_url
            != classify_url(self.source_url, frozenset({"synthetic.publisher.example"})).normalized
        ):
            raise ValueError("Canonical durable source URL required")
        for identifier in (self.identifier, *self.aliases):
            ProviderRequest(article=identifier, view="FULL")
        if len(set((i.kind, i.value) for i in (self.identifier, *self.aliases))) != 1 + len(
            self.aliases
        ):
            raise ValueError("Unique identifier bindings required")
        return self

    @property
    def request(self) -> ProviderRequest:
        return ProviderRequest(article=self.identifier, view="FULL")


def documents(support: object, source_id: str) -> tuple[ProviderDocument, ...]:
    if not isinstance(support, dict) or not isinstance(support.get("provider_documents"), list):
        raise FetchDenied("provider_document_registry_unavailable")
    values = support["provider_documents"]
    if not 1 <= len(values) <= 500:
        raise FetchDenied("provider_document_registry_denied")
    result = tuple(ProviderDocument.model_validate_json(json.dumps(value)) for value in values)
    if any(value.source_id != source_id for value in result) or len(
        {v.source_url for v in result}
    ) != len(result):
        raise FetchDenied("provider_document_registry_denied")
    return result


def for_article(registry: tuple[ProviderDocument, ...], article: SearchArticle) -> ProviderDocument:
    ids = {
        (kind, value)
        for kind, value in (("doi", article.doi), ("pii", article.pii))
        if value is not None
    }
    found = [d for d in registry if ids & {(i.kind, i.value) for i in (d.identifier, *d.aliases)}]
    if len(found) != 1 or not ids <= {
        (i.kind, i.value) for i in (found[0].identifier, *found[0].aliases)
    }:
        raise FetchDenied("provider_document_identity_denied")
    return found[0]
