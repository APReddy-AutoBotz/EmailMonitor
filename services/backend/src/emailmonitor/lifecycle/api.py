"""Test-only current-owner/steward lifecycle; synthetic records only."""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from emailmonitor.config import Settings
from emailmonitor.lifecycle.models import (
    DeletionReceipt,
    DeletionRequest,
    RetentionState,
    RetentionUpdate,
    SupportContext,
    SupportCreate,
    SupportInspection,
    Suppression,
    SuppressionCreate,
)
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import Database


def lifecycle_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/organizations/{organization_id}/privacy")

    def service(request: Request, write: bool = True) -> Lifecycle:
        if settings.environment != "test" or not settings.fixture_mode:
            raise HTTPException(503, "Synthetic lifecycle unavailable")
        return Lifecycle(database, (csrf if write else token)(request), settings)

    @router.get("/retention", response_model=RetentionState)
    def retention(request: Request, organization_id: UUID) -> RetentionState:
        return service(request, False).retention(organization_id)

    @router.patch("/retention", response_model=RetentionState)
    def update_retention(
        request: Request, organization_id: UUID, body: RetentionUpdate
    ) -> RetentionState:
        return service(request).update_retention(organization_id, body)

    @router.post("/suppressions", response_model=Suppression, status_code=201)
    def suppress(request: Request, organization_id: UUID, body: SuppressionCreate) -> Suppression:
        return service(request).suppress(organization_id, body)

    @router.post("/suppressions/{identifier}/withdraw", response_model=Suppression)
    def withdraw(request: Request, organization_id: UUID, identifier: UUID) -> Suppression:
        return service(request).withdraw(organization_id, identifier)

    @router.post("/deletions", response_model=DeletionReceipt, status_code=201)
    def stage(request: Request, organization_id: UUID, body: DeletionRequest) -> DeletionReceipt:
        return service(request).stage(organization_id, body)

    @router.post("/deletions/{identifier}/purge", response_model=DeletionReceipt)
    def purge(request: Request, organization_id: UUID, identifier: UUID) -> DeletionReceipt:
        return service(request).purge(organization_id, identifier)

    @router.post("/retention/tick")
    def tick(request: Request, organization_id: UUID) -> dict[str, int]:
        return {"purged_jobs": service(request).tick(organization_id)}

    @router.post("/support-contexts", response_model=SupportContext, status_code=201)
    def support(request: Request, organization_id: UUID, body: SupportCreate) -> SupportContext:
        return service(request).approve_support(organization_id, body)

    @router.post("/support-contexts/{identifier}/revoke", response_model=SupportContext)
    def revoke(request: Request, organization_id: UUID, identifier: UUID) -> SupportContext:
        return service(request).revoke_support(organization_id, identifier)

    @router.post("/support-contexts/{identifier}/inspect", response_model=SupportInspection)
    def inspect(request: Request, organization_id: UUID, identifier: UUID) -> SupportInspection:
        # Inspection appends an audit event, so CSRF is required even for metadata.
        return service(request).inspect_support(organization_id, identifier)

    return router
