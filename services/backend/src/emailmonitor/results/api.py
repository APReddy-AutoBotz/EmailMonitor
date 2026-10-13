"""Identifier/options-only retained results and authenticated private exports."""

from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.config import Settings
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.organizations.database import Database, RevisionConflict
from emailmonitor.results.models import (
    Contact,
    ContactPage,
    EvidenceView,
    ExportInput,
    ExportState,
    Filters,
    OutcomePage,
)
from emailmonitor.results.service import Results


class Revocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


def result_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    settings: Settings,
) -> APIRouter:
    router = APIRouter()

    def service(session: str) -> Results:
        try:
            return Results(database, session, settings)
        except FetchDenied as error:
            raise HTTPException(404, "Resource unavailable") from error

    @router.get("/organizations/{organization_id}/contacts")
    def contacts(
        request: Request,
        organization_id: UUID,
        job_id: UUID | None = None,
        state: Annotated[
            list[Literal["accepted", "needs_review", "unmatched", "rejected"]] | None, Query()
        ] = None,
        author_target: Literal["all", "first", "corresponding"] = "all",
        query: str = Query(default="", max_length=100),
        cursor: str | None = Query(default=None, max_length=2048),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> ContactPage:
        try:
            filters = Filters(
                job_id=job_id,
                states=tuple(state) if state is not None else ("accepted",),
                author_target=author_target,
                query=query,
            )
            return service(token(request)).contacts(organization_id, filters, cursor, limit)
        except ValueError as error:
            raise HTTPException(422, "Bounded tenant/filter cursor required") from error

    @router.get("/organizations/{organization_id}/contacts/{association_id}")
    def contact(
        request: Request, organization_id: UUID, association_id: UUID, batch_id: UUID
    ) -> Contact:
        return service(token(request)).contact(organization_id, batch_id, association_id)

    @router.get("/organizations/{organization_id}/article-outcomes")
    def outcomes(
        request: Request,
        organization_id: UUID,
        job_id: UUID | None = None,
        cursor: str | None = Query(default=None, max_length=2048),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> OutcomePage:
        try:
            return service(token(request)).outcomes(organization_id, job_id, cursor, limit)
        except ValueError as error:
            raise HTTPException(422, "Bounded tenant/filter cursor required") from error

    @router.get("/organizations/{organization_id}/evidence/{evidence_id}")
    def evidence(
        request: Request, organization_id: UUID, evidence_id: UUID, batch_id: UUID
    ) -> EvidenceView:
        return service(token(request)).evidence(organization_id, batch_id, evidence_id)

    @router.post("/organizations/{organization_id}/exports/preview")
    def export_preview(request: Request, organization_id: UUID, body: ExportInput) -> object:
        return Results(database, csrf(request), settings).preview(organization_id, body)

    @router.post("/organizations/{organization_id}/exports", status_code=201)
    def create(
        request: Request,
        organization_id: UUID,
        body: ExportInput,
        idempotency_key: str = Header(min_length=1, max_length=200),
    ) -> ExportState:
        try:
            return service(csrf(request)).create(organization_id, body, idempotency_key)
        except RevisionConflict as error:
            raise HTTPException(409, "Export idempotency conflict") from error
        except ValueError as error:
            raise HTTPException(422, "Bounded export options required") from error

    @router.get("/organizations/{organization_id}/exports")
    def exports(request: Request, organization_id: UUID) -> tuple[ExportState, ...]:
        return service(token(request)).exports(organization_id)

    @router.get("/organizations/{organization_id}/exports/{export_id}")
    def status(request: Request, organization_id: UUID, export_id: UUID) -> ExportState:
        return service(token(request)).state(organization_id, export_id)

    @router.post("/organizations/{organization_id}/exports/{export_id}/revoke")
    def revoke(
        request: Request, organization_id: UUID, export_id: UUID, body: Revocation
    ) -> ExportState:
        try:
            return service(csrf(request)).revoke(organization_id, export_id, body.expected_revision)
        except RevisionConflict as error:
            raise HTTPException(409, "Export revision conflict") from error

    @router.get("/organizations/{organization_id}/exports/{export_id}/download")
    def download(request: Request, organization_id: UUID, export_id: UUID) -> Response:
        artifact = service(token(request)).download(organization_id, export_id)
        filename = f"export-{export_id}.{artifact.extension}"
        return Response(
            content=artifact.body,
            media_type=artifact.content_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    return router
