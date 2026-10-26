"""Current-authorized retained article metadata; no inferred dates or identities."""

import json
from typing import Literal
from uuid import UUID

from pydantic import Field

from emailmonitor.associations.models import Bundle, Record
from emailmonitor.associations.quality import SourceBinding, project_quality
from emailmonitor.extraction.html import ArticleObservation, MetadataFact, MetadataValues
from emailmonitor.extraction.pdf import PdfMetadata
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.xml_retained import RetainedXml


class ArticleMetadata(Record):
    view_version: Literal["article-metadata-v1"] = "article-metadata-v1"
    scope: Literal["article"] = "article"
    organization_id: UUID
    batch_id: UUID
    source_url: str = Field(min_length=1, max_length=2048)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1, max_length=64)
    observation_route: Literal["html", "browser_dom", "pdf", "article_xml"]
    preferred_metadata: MetadataValues
    facts: tuple[MetadataFact | PdfMetadata, ...] = Field(max_length=100)
    fact_availability: Literal["recorded", "not_recorded"]
    multiple_value_fields: tuple[Literal["title", "journal", "publication_date", "doi"], ...]
    date_interpretation: Literal["retained_text_and_recorded_type_only"] = (
        "retained_text_and_recorded_type_only"
    )


def project_metadata(
    org: UUID, batch: UUID, bundle: Bundle, document: object, source: SourceBinding
) -> ArticleMetadata:
    # Reuse the exact source/batch/profile binding validation, not its summary.
    project_quality(org, batch, bundle, document, source)
    assert isinstance(document, dict)
    observation: ArticleObservation | RetainedPdf | RetainedXml
    if document.get("route") == "pdf":
        observation = RetainedPdf.model_validate_json(json.dumps(document))
    elif document.get("route") == "article_xml":
        observation = RetainedXml.model_validate_json(json.dumps(document))
    else:
        observation = ArticleObservation.model_validate_json(json.dumps(document))
    if observation.preferred_metadata != bundle.preferred_metadata:
        raise ValueError("Metadata must match its retained association snapshot")
    facts: tuple[MetadataFact | PdfMetadata, ...]
    if isinstance(observation, RetainedXml):
        facts = ()
    elif isinstance(observation, RetainedPdf):
        facts = tuple(observation.metadata)
    else:
        facts = tuple(observation.metadata)
    fields: tuple[Literal["title", "journal", "publication_date", "doi"], ...] = (
        "title",
        "journal",
        "publication_date",
        "doi",
    )
    return ArticleMetadata(
        organization_id=org,
        batch_id=batch,
        source_url=bundle.source_url,
        content_digest=bundle.content_digest,
        parser_version=bundle.parser_version,
        observation_route=bundle.observation_route,
        preferred_metadata=observation.preferred_metadata,
        facts=facts,
        fact_availability="not_recorded" if isinstance(observation, RetainedXml) else "recorded",
        multiple_value_fields=tuple(
            field
            for field in fields
            if len({fact.value for fact in facts if fact.field == field}) > 1
        ),
    )
