"""Public metadata endpoints only; tenant data APIs await EM-002."""

import os
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from emailmonitor.config import Settings


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    implementation_stage: Literal["scaffold"] = "scaffold"
    extraction_implemented: Literal[False] = False
    live_sources_enabled: Literal[False] = False
    outbound_email_enabled: Literal[False] = False
    external_ai_enabled: Literal[False] = False
    tenant_data_api_available: Literal[False] = False


def create_app(settings: Settings | None = None) -> FastAPI:
    validated = settings or Settings.from_environment(os.environ)
    application = FastAPI(title="EmailMonitor", version="0.1.0", docs_url=None, redoc_url=None)
    application.state.settings = validated

    @application.get("/healthz", response_model=Health)
    def health() -> Health:
        return Health()

    @application.get("/api/v1/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        return Capabilities()

    return application


app = create_app()
