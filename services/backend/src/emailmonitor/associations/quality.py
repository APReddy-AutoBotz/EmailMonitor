"""Read-only article quality projection; never changes stored association facts."""

import json
from dataclasses import dataclass
from typing import Literal, cast, get_args
from uuid import UUID

from pydantic import Field, model_validator

from emailmonitor.associations.models import Bundle, Record
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.sciencedirect import Reason
from emailmonitor.extraction.xml_retained import RetainedXml

type PdfQualityReason = Literal[
    "page_cap",
    "encrypted",
    "corrupt",
    "image_only_or_no_extractable_text",
    "unsupported_geometry",
    "unsupported_font_or_structure",
    "resource_limit",
    "deadline",
]


class ObservationQuality(Record):
    view_version: Literal["observation-quality-v1"] = "observation-quality-v1"
    organization_id: UUID
    batch_id: UUID
    scope: Literal["article"] = "article"
    parser_version: Literal[
        "elsevier-xml-head-v1", "synthetic-html-v1", "pypdf-6.20.1-synthetic-v1"
    ]
    observation_route: Literal["article_xml", "html", "browser_dom", "pdf"]
    observation_status: Literal[
        "observed", "no_contact", "requires_browser", "partial", "unsupported"
    ]
    reason_availability: Literal["recorded", "not_recorded"]
    reasons: tuple[
        Reason
        | Literal[
            "page_cap",
            "encrypted",
            "corrupt",
            "image_only_or_no_extractable_text",
            "unsupported_geometry",
            "unsupported_font_or_structure",
            "resource_limit",
            "deadline",
        ],
        ...,
    ] = Field(max_length=20)
    review_scope: Literal["author_email_association"] = "author_email_association"

    @model_validator(mode="after")
    def compatible_profile(self) -> "ObservationQuality":
        if self.observation_route == "article_xml":
            if (
                self.parser_version != "elsevier-xml-head-v1"
                or any(reason not in get_args(Reason) for reason in self.reasons)
                or self.reason_availability != "recorded"
                or self.observation_status == "requires_browser"
                or bool(self.reasons) != (self.observation_status in {"partial", "unsupported"})
            ):
                raise ValueError("Recorded XML quality must retain its original outcome")
        elif self.observation_route == "pdf":
            if (
                self.parser_version != "pypdf-6.20.1-synthetic-v1"
                or any(
                    reason not in get_args(PdfQualityReason.__value__) for reason in self.reasons
                )
                or self.reason_availability != "recorded"
                or self.observation_status == "requires_browser"
                or bool(self.reasons) != (self.observation_status in {"partial", "unsupported"})
            ):
                raise ValueError("Recorded PDF quality must preserve the parsed outcome")
        elif (
            self.parser_version != "synthetic-html-v1"
            or self.reason_availability != "not_recorded"
            or self.reasons
            or self.observation_status not in {"observed", "no_contact", "requires_browser"}
        ):
            raise ValueError("HTML quality reasons are not recorded by this profile")
        return self


@dataclass(frozen=True)
class SourceBinding:
    job: UUID
    generation: int
    policy_version: int
    deletion_generation: int


def project_quality(
    org: UUID, batch: UUID, bundle: Bundle, document: object, source: SourceBinding
) -> ObservationQuality:
    """Consume validated retained facts, not raw XML or newly inferred associations."""
    bundle = Bundle.model_validate_json(bundle.model_dump_json())
    if bundle.organization_id != org or not isinstance(document, dict):
        raise ValueError("Same-organization retained observation required")
    observation: RetainedXml | ArticleObservation | RetainedPdf
    if document.get("route") in {"article_xml", "pdf"}:
        observation = (
            RetainedPdf.model_validate_json(json.dumps(document))
            if document.get("route") == "pdf"
            else RetainedXml.model_validate_json(json.dumps(document))
        )
        if (
            observation.binding.organization != org
            or observation.binding.job != source.job
            or observation.binding.generation != source.generation
            or observation.binding.policy_version != source.policy_version
            or observation.binding.deletion_generation != source.deletion_generation
        ):
            raise ValueError("Same-organization XML binding required")
    elif document.get("route") in {"html", "browser_dom"}:
        observation = ArticleObservation.model_validate_json(json.dumps(document))
    else:
        raise ValueError("Supported retained profile required")
    if (
        observation.url != bundle.source_url
        or observation.content_digest != bundle.content_digest
        or observation.parser_version != bundle.parser_version
        or observation.route != bundle.observation_route
        or observation.status != bundle.observation_status
    ):
        raise ValueError("Quality must match the original batch observation")
    return ObservationQuality(
        organization_id=org,
        batch_id=batch,
        parser_version=observation.parser_version,
        observation_route=observation.route,
        observation_status=observation.status,
        reason_availability="recorded"
        if isinstance(observation, (RetainedXml, RetainedPdf))
        else "not_recorded",
        reasons=tuple(observation.reasons)
        if isinstance(observation, RetainedXml)
        else (
            (cast(PdfQualityReason, observation.reason),)
            if isinstance(observation, RetainedPdf)
            and observation.reason not in {"complete", "byte_cap", "pdf_disabled"}
            else ()
        ),
    )
