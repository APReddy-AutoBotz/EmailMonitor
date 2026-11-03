"""Transient review context only: no identity assertion or durable attachment."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from emailmonitor.associations.models import Bundle, Evidence, Record
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict


class ContextView(Record):
    kind: Literal["transient_context_only"] = "transient_context_only"
    organization_id: UUID
    target_batch_id: UUID
    target_association_id: UUID
    target_revision: int = Field(ge=1)
    source_batch_id: UUID
    source_url: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_parser_version: str
    source_route: Literal["html", "browser_dom", "pdf", "article_xml"]
    evidence: Evidence
    attached: Literal[False] = False
    identity_verified: Literal[False] = False
    acceptance_changed: Literal[False] = False
    export_changed: Literal[False] = False


def project_context(
    org: UUID,
    target_batch: UUID,
    target: Bundle,
    association_id: UUID,
    revision: int,
    source_batch: UUID,
    source: Bundle,
    evidence_id: UUID,
) -> ContextView:
    """Project already-authorized bundles; this function does not grant access."""
    # Revalidation prevents constructing altered instances through model_copy.
    target = Bundle.model_validate_json(target.model_dump_json())
    source = Bundle.model_validate_json(source.model_dump_json())
    if (
        target_batch == source_batch
        or target.organization_id != org
        or source.organization_id != org
    ):
        raise AuthorizationDenied()
    association = next((row for row in target.associations if row.id == association_id), None)
    evidence = next((row for row in source.evidence if row.id == evidence_id), None)
    if association is None or evidence is None or association.state == "suppressed":
        raise AuthorizationDenied()
    if association.revision != revision:
        raise RevisionConflict()
    return ContextView(
        organization_id=org,
        target_batch_id=target_batch,
        target_association_id=association_id,
        target_revision=revision,
        source_batch_id=source_batch,
        source_url=source.source_url,
        source_digest=source.content_digest,
        source_parser_version=source.parser_version,
        source_route=source.observation_route,
        evidence=evidence,
    )
