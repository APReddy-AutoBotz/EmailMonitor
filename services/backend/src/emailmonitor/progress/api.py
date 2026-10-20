"""Identifier-only synthetic start/control and authenticated bounded metadata SSE."""

from collections.abc import Callable
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from starlette.responses import StreamingResponse

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.database import AuthorizationDenied, Database, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.models import Item, Snapshot
from emailmonitor.progress.service import Progress
from emailmonitor.progress.state import parse_cursor
from emailmonitor.progress.stream import replay
from emailmonitor.runtime.delegation import ServiceBindings


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)


def progress_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    settings: Settings,
    bindings: ServiceBindings | None = None,
) -> APIRouter:
    router = APIRouter()

    def service(request: Request, mutation: bool = False) -> Progress:
        try:
            require_fixture(settings)
        except FetchDenied as error:
            raise HTTPException(404, "Synthetic execution unavailable") from error
        return Progress(
            database, csrf(request) if mutation else token(request), settings, bindings=bindings
        )

    @router.post("/organizations/{organization_id}/jobs/{job_id}/start", response_model=Snapshot)
    def start(request: Request, organization_id: UUID, job_id: UUID, body: Revision) -> Snapshot:
        try:
            return service(request, True).start(organization_id, job_id, body.expected_revision)
        except RevisionConflict as error:
            raise HTTPException(409, "Job revision conflict") from error

    @router.post("/organizations/{organization_id}/jobs/{job_id}/retry", status_code=201)
    def retry(
        request: Request, organization_id: UUID, job_id: UUID, body: Revision
    ) -> dict[str, UUID]:
        try:
            continuation = service(request, True).retry(
                organization_id, job_id, body.expected_revision
            )
            return {"job_id": continuation}
        except RevisionConflict as error:
            raise HTTPException(409, "Job revision conflict") from error

    @router.get("/organizations/{organization_id}/jobs/{job_id}/progress", response_model=Snapshot)
    def progress(request: Request, organization_id: UUID, job_id: UUID) -> Snapshot:
        return service(request).snapshot(organization_id, job_id)

    @router.get(
        "/organizations/{organization_id}/jobs/{job_id}/progress/items", response_model=list[Item]
    )
    def items(request: Request, organization_id: UUID, job_id: UUID) -> list[Item]:
        return service(request).items(organization_id, job_id)

    @router.get("/organizations/{organization_id}/jobs/{job_id}/events")
    def events(request: Request, organization_id: UUID, job_id: UUID) -> StreamingResponse:
        reader = service(request)
        try:
            after = parse_cursor(organization_id, job_id, request.headers.get("Last-Event-ID"))
            reader.events(organization_id, job_id, after)  # authenticate before HTTP 200/headers
        except ValueError as error:
            raise HTTPException(409, "Invalid tenant/job replay cursor") from error
        return StreamingResponse(
            replay(reader, organization_id, job_id, after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    def control(
        request: Request,
        org: UUID,
        job: UUID,
        body: Revision,
        action: Literal["pause", "resume", "cancel"],
    ) -> dict[str, bool]:
        credential = csrf(request)
        with database.tenant(credential, org, Capability.ACQUIRE_SOURCE) as (connection, _):
            row = connection.execute(
                text(
                    "SELECT kind,state FROM emailmonitor.jobs "
                    "WHERE organization_id=:org AND id=:job"
                ),
                {"org": org, "job": job},
            ).first()
            if row is None:
                raise AuthorizationDenied()
            kind, state = row
        try:
            if kind == "fixture_probe" or (state == "draft" and action == "cancel"):
                Ledger(database, credential, settings).control(
                    org, job, action, body.expected_revision
                )
            else:
                service(request, True).control(org, job, body.expected_revision, action)
        except RevisionConflict as error:
            raise HTTPException(409, "Job revision conflict/state") from error
        return {"updated": True}

    @router.post("/organizations/{organization_id}/jobs/{job_id}/pause")
    def pause(
        request: Request, organization_id: UUID, job_id: UUID, body: Revision
    ) -> dict[str, bool]:
        return control(request, organization_id, job_id, body, "pause")

    @router.post("/organizations/{organization_id}/jobs/{job_id}/resume")
    def resume(
        request: Request, organization_id: UUID, job_id: UUID, body: Revision
    ) -> dict[str, bool]:
        return control(request, organization_id, job_id, body, "resume")

    @router.post("/organizations/{organization_id}/jobs/{job_id}/cancel")
    def cancel(
        request: Request, organization_id: UUID, job_id: UUID, body: Revision
    ) -> dict[str, bool]:
        return control(request, organization_id, job_id, body, "cancel")

    return router
