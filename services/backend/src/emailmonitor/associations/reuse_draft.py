"""Offline construction only; this does not authorize or persist reuse."""

from uuid import UUID

from emailmonitor.associations.mapping import identifier, map_observation
from emailmonitor.associations.models import Bundle
from emailmonitor.config import Settings
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.xml_retained import RetainedXml


def independent_review_draft(
    settings: Settings,
    organization: UUID,
    source_organization: UUID,
    source_job: UUID,
    target_job: UUID,
    observation: ArticleObservation | RetainedPdf | RetainedXml,
) -> Bundle:
    """Rebuild from observed facts, never from another job's reviewed batch.

    This pure draft is not an authorization or proof of freshness, retention,
    suppression, current source policy, or a durable source-to-target link.
    No route or worker may execute reuse on the strength of this value alone.
    """
    if not all(
        type(value) is UUID for value in (organization, source_organization, source_job, target_job)
    ):
        raise ValueError("Exact scoped identifiers required")
    if organization != source_organization or source_job == target_job:
        raise ValueError("Same tenant and independent jobs required")
    if isinstance(observation, (RetainedPdf, RetainedXml)) and (
        observation.binding.organization != source_organization
        or observation.binding.job != source_job
    ):
        raise ValueError("Retained observation binding mismatch")
    mapped = map_observation(settings, organization, observation)
    document = mapped.model_dump(mode="python")
    for association in document["associations"]:
        association["id"] = identifier(
            organization,
            "reuse-association",
            str(source_job),
            str(target_job),
            str(association["id"]),
        )
        if association["state"] == "accepted":
            association.update(
                state="needs_review", evidence_strength="ambiguous", reason="structural_hint"
            )
    return Bundle.model_validate(document)
