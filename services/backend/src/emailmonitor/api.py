"""Public metadata endpoints only; tenant data APIs await EM-002."""

import os
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from emailmonitor.config import Settings
from emailmonitor.identity.foundation import Foundation
from emailmonitor.organizations.database import AuthorizationDenied


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    implementation_stage: Literal["scaffold", "tenant_foundation", "source_policy"] = "scaffold"
    extraction_implemented: Literal[False] = False
    live_sources_enabled: Literal[False] = False
    outbound_email_enabled: Literal[False] = False
    external_ai_enabled: Literal[False] = False
    tenant_data_api_available: bool = False


def create_app(settings: Settings | None = None, foundation: Foundation | None = None) -> FastAPI:
    validated = settings or Settings.from_environment(os.environ)
    application = FastAPI(title="EmailMonitor", version="0.1.0", docs_url=None, redoc_url=None)
    application.state.settings = validated

    @application.get("/healthz", response_model=Health)
    def health() -> Health:
        return Health()

    @application.get("/api/v1/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        return Capabilities(
            implementation_stage="source_policy" if foundation else "scaffold",
            tenant_data_api_available=foundation is not None,
        )

    if foundation is not None:
        application.include_router(foundation.router(validated))

        @application.middleware("http")
        async def prevent_identity_caching(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

    @application.exception_handler(AuthorizationDenied)
    async def unavailable_resource(request: Request, error: AuthorizationDenied) -> JSONResponse:
        return JSONResponse({"detail": "Resource unavailable"}, status_code=404)

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Operation conflict or dependency unavailable"}, status_code=409
        )

    return application


app = create_app()
