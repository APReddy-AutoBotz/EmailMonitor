"""Bounded existing-owner configuration; no access grants or payment configuration."""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from emailmonitor.administration.models import Configuration, ConfigurationUpdate, ResourceUsage
from emailmonitor.administration.service import Administration
from emailmonitor.config import Settings
from emailmonitor.organizations.database import Database


def administration_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    settings: Settings,
) -> APIRouter:
    router = APIRouter()

    def available() -> None:
        if settings.environment != "test" or not settings.fixture_mode:
            raise HTTPException(503, "Synthetic configuration unavailable")

    @router.get("/organizations/{organization_id}/configuration", response_model=Configuration)
    def read(request: Request, organization_id: UUID) -> Configuration:
        available()
        return Administration(database, token(request), settings).read(organization_id)

    @router.get("/organizations/{organization_id}/resource-usage", response_model=ResourceUsage)
    def usage(request: Request, organization_id: UUID) -> ResourceUsage:
        available()
        return Administration(database, token(request), settings).usage(organization_id)

    @router.patch("/organizations/{organization_id}/configuration", response_model=Configuration)
    def update(request: Request, organization_id: UUID, body: ConfigurationUpdate) -> Configuration:
        available()
        return Administration(database, csrf(request), settings).update(organization_id, body)

    return router
