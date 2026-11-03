"""Current-authorized retained article metadata; no inferred dates or identities."""

import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from emailmonitor.associations.date_precision import DatePrecision, retained_date_precision
from emailmonitor.associations.models import Bundle, Record
from emailmonitor.associations.quality import SourceBinding, project_quality
from emailmonitor.extraction.html import ArticleObservation, MetadataFact, MetadataValues
from emailmonitor.extraction.pdf import PdfMetadata
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.xml_retained import RetainedXml


class RetainedDatePrecision(Record):
    fact_index: int = Field(ge=0, le=99)
    precision: DatePrecision


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


class ArticleMetadataPrecision(Record):
    view_version: Literal["article-metadata-precision-v1"] = "article-metadata-precision-v1"
    metadata: ArticleMetadata
    date_precisions: tuple[RetainedDatePrecision, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def precision_matches_retained_facts(self) -> "ArticleMetadataPrecision":
        expected = tuple(
            RetainedDatePrecision(fact_index=index, precision=retained_date_precision(fact.value))
            for index, fact in enumerate(self.metadata.facts)
            if fact.field == "publication_date"
        )
        if self.date_precisions != expected:
            raise ValueError("Date precision must describe the exact retained text")
        return self


def project_metadata_precision(metadata: ArticleMetadata) -> ArticleMetadataPrecision:
    return ArticleMetadataPrecision(
        metadata=metadata,
        date_precisions=tuple(
            RetainedDatePrecision(fact_index=index, precision=retained_date_precision(fact.value))
            for index, fact in enumerate(metadata.facts)
            if fact.field == "publication_date"
        ),
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
