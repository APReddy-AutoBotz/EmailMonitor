"""Owned API process composition with explicit existing service bindings."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from emailmonitor.api import create_app
from emailmonitor.identity.foundation import Foundation
from emailmonitor.identity.oidc import OIDCProvider
from emailmonitor.organizations.database import AuthenticationDatabase, Database
from emailmonitor.runtime.assembly import TestRuntimeConfig, _Admission, _AdmissionMiddleware
from emailmonitor.runtime.delegation import ServiceBindings


@dataclass(frozen=True)
class ServiceAPIConfig:
    runtime: TestRuntimeConfig
    bindings: ServiceBindings


@contextmanager
def service_api(config: ServiceAPIConfig, provider: OIDCProvider) -> Iterator[FastAPI]:
    """Caller owns listener lifetime; the API owns exactly its two SQL pools.

    Existing test-only OIDC verification is preserved. Production activation needs
    a reviewed exchange adapter and real registration outside this code milestone.
    No publisher pool or service login is opened in the human API process.
    """
    validated = TestRuntimeConfig(
        settings=config.runtime.settings,
        runtime_database_url=config.runtime.runtime_database_url,
        authentication_database_url=config.runtime.authentication_database_url,
    )
    bindings = ServiceBindings.model_validate(config.bindings.model_dump())
    if not bindings.tenants:
        raise ValueError("Explicit tenant service bindings required")
    database = authentication = None
    admission = _Admission()
    try:
        database = Database(validated.runtime_database_url)
        authentication = AuthenticationDatabase(validated.authentication_database_url)

        def ready() -> bool:
            assert database is not None
            try:
                assert authentication is not None
                with authentication.transaction() as connection:
                    if not connection.execute(
                        text(
                            "SELECT has_function_privilege(current_user,"
                            "'emailmonitor.establish_session(text,text,text,text)','EXECUTE')"
                        )
                    ).scalar_one():
                        return False
                with database.transaction() as connection:
                    return all(
                        bool(
                            connection.execute(
                                text(
                                    "SELECT emailmonitor.service_api_binding_ready("
                                    ":org,:worker,:publisher)"
                                ),
                                {
                                    "org": entry.organization,
                                    "worker": entry.worker,
                                    "publisher": entry.publisher,
                                },
                            ).scalar_one()
                        )
                        for entry in bindings.tenants
                    )
            except Exception:
                return False

        if not ready():
            raise ValueError("Exact service schema and registered bindings required")
        foundation = Foundation(database, provider, authentication, bindings)
        application = create_app(validated.settings, foundation)
        application.add_middleware(_AdmissionMiddleware, admission=admission)

        @application.get("/api/v1/runtime-profile", include_in_schema=False)
        def profile() -> dict[str, object]:
            return {
                "profile": "authored-html-service-reference",
                "production_ready": False,
                "xml_available": False,
                "pdf_available": False,
                "dynamic_browser_available": False,
                "live_sources_available": False,
            }

        @application.get("/readyz", include_in_schema=False)
        def readiness() -> JSONResponse:
            available = ready()
            return JSONResponse(
                {"api_dependencies_ready": available},
                status_code=200 if available else 503,
                headers={"Cache-Control": "no-store"},
            )

        yield application
    finally:
        admission.active = False
        try:
            if authentication is not None:
                authentication.engine.dispose()
        finally:
            if database is not None:
                database.engine.dispose()
