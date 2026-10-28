"""Identifier-only synthetic association/review endpoints; no content ingestion."""

import re
from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from emailmonitor.associations.metadata import ArticleMetadata
from emailmonitor.associations.models import Bundle, Review
from emailmonitor.associations.quality import ObservationQuality
from emailmonitor.associations.service import Associations
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.organizations.database import Database, RevisionConflict


def canonical_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
        )
        is None
    ):
        raise ValueError("Canonical UUID identifier required")
    return UUID(value)


Identifier = Annotated[UUID, BeforeValidator(canonical_uuid)]


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_url: Literal[
        "https://synthetic.publisher.example/article-a.html",
        "https://synthetic.publisher.example/article-b.html",
        "https://synthetic.publisher.example/tooltip.html",
        "https://synthetic.publisher.example/no-contact.html",
    ]
    expected_observation_revision: int = Field(ge=1, strict=True)


class ReviewInput(BaseModel):
    # UUID text is normal HTTP JSON; the internal model receives parsed UUIDs.
    model_config = ConfigDict(extra="forbid")
    batch_id: Identifier
    association_id: Identifier
    expected_revision: int = Field(ge=1, strict=True)
    action: Literal["accept", "reject", "correct", "unlink"]
    author_id: Identifier | None = None
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=300, pattern=r"\S", strict=True)

    def internal(self) -> Review:
        return Review(
            association_id=self.association_id,
            expected_revision=self.expected_revision,
            action=self.action,
            author_id=self.author_id,
            evidence_ids=tuple(self.evidence_ids),
            reason=self.reason,
        )


def association_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    settings: Settings,
) -> APIRouter:
    router = APIRouter()

    def service_for(session: str) -> Associations:
        try:
            require_fixture(settings)
        except FetchDenied as error:
            raise HTTPException(404, "Resource unavailable") from error
        return Associations(database, session, settings)

    @router.post("/organizations/{organization_id}/jobs/{job_id}/associations", status_code=201)
    def derive(
        request: Request, organization_id: UUID, job_id: UUID, body: Selection
    ) -> dict[str, str]:
        service = service_for(csrf(request))
        try:
            batch = service.derive(
                organization_id, job_id, body.article_url, body.expected_observation_revision
            )
        except RevisionConflict as error:
            raise HTTPException(409, "Observation revision conflict") from error
        except ValueError as error:
            raise HTTPException(422, "Bounded retained observation required") from error
        return {"batch_id": str(batch), "state": "observed"}

    @router.get("/organizations/{organization_id}/jobs/{job_id}/associations")
    def batches(request: Request, organization_id: UUID, job_id: UUID) -> list[dict[str, object]]:
        return service_for(token(request)).batches(organization_id, job_id)

    @router.get("/organizations/{organization_id}/association-batches/{batch_id}")
    def detail(request: Request, organization_id: UUID, batch_id: UUID) -> Bundle:
        return service_for(token(request)).detail(organization_id, batch_id)

    @router.get("/organizations/{organization_id}/association-batches/{batch_id}/article-metadata")
    def metadata(request: Request, organization_id: UUID, batch_id: UUID) -> ArticleMetadata:
        return service_for(token(request)).metadata(organization_id, batch_id)

    @router.get(
        "/organizations/{organization_id}/association-batches/{batch_id}/observation-quality"
    )
    def quality(request: Request, organization_id: UUID, batch_id: UUID) -> ObservationQuality:
        return service_for(token(request)).quality(organization_id, batch_id)

    @router.post("/organizations/{organization_id}/reviews")
    def review(request: Request, organization_id: UUID, body: ReviewInput) -> Bundle:
        service = service_for(csrf(request))
        try:
            result = service.review(organization_id, body.batch_id, body.internal())
        except RevisionConflict as error:
            raise HTTPException(409, "Association revision conflict") from error
        except ValueError as error:
            raise HTTPException(
                422, "Current observed author/address citations required"
            ) from error
        return result

    @router.get("/organizations/{organization_id}/association-batches/{batch_id}/reviews")
    def history(request: Request, organization_id: UUID, batch_id: UUID) -> list[dict[str, object]]:
        return service_for(token(request)).history(organization_id, batch_id)

    return router
