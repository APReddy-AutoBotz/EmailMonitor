"""Own three disposable test pools without activating a deployment or worker.

Callers must stop their publisher and quiesce requests before leaving the context.
The close gate refuses later HTTP admissions; it does not drain active requests,
cancel work, impose a shutdown deadline or own Celery/broker resources.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url
from starlette.types import ASGIApp, Receive, Scope, Send

from emailmonitor.api import create_app
from emailmonitor.config import Settings
from emailmonitor.identity.foundation import Foundation
from emailmonitor.identity.oidc import OIDCProvider
from emailmonitor.organizations.database import AuthenticationDatabase, Database


class RuntimeAssemblyError(RuntimeError):
    """Fixed public failure, without connection strings or constructor details."""


class RuntimeCleanupError(RuntimeError):
    """All registered disposals were attempted, but at least one failed."""


def _validated_settings(settings: Settings) -> Settings:
    try:
        if type(settings) is not Settings:
            raise ValueError
        validated = Settings.model_validate(settings.model_dump(warnings="error"))
        if (
            validated.environment != "test"
            or validated.fixture_mode is not True
            or validated.identity_stub is not True
        ):
            raise ValueError
        return validated
    except Exception:
        raise ValueError("Explicit valid test fixture and identity settings required") from None


def _database_target(value: str) -> tuple[str, int, str, str]:
    try:
        if type(value) is not str or any(character.isspace() for character in value):
            raise ValueError
        parsed = urlsplit(value)
        url = make_url(value)
        if (
            parsed.scheme != "postgresql+pg8000"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or "?" in value
            or "#" in value
            or url.drivername != "postgresql+pg8000"
            or url.host != "127.0.0.1"
            or url.port != parsed.port
            or not url.username
            or not url.password
            or not url.database
            or "/" in url.database
            or url.query
        ):
            raise ValueError
        return url.host, url.port, url.database, url.username
    except Exception:
        raise ValueError("Explicit disposable loopback PostgreSQL URL required") from None


@dataclass(frozen=True, slots=True, kw_only=True)
class TestRuntimeConfig:
    """Trusted Python input, never an environment/JSON/import activation selector.

    This configuration does not establish that a database is disposable. Its
    trusted caller supplies an already provisioned disposable test database.
    Runtime and authenticator authority is checked by the existing SQL constructors.
    """

    settings: Settings = field(repr=False)
    runtime_database_url: str = field(repr=False)
    authentication_database_url: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _validated_settings(self.settings))
        runtime = _database_target(self.runtime_database_url)
        authentication = _database_target(self.authentication_database_url)
        if runtime[:3] != authentication[:3] or runtime[3] == authentication[3]:
            raise ValueError("Separate logins for the same disposable database required")


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    """API and publisher resources borrowed until their owning context exits."""

    app: FastAPI = field(repr=False)
    api_database: Database = field(repr=False)
    publisher_database: Database = field(repr=False)


@dataclass
class _Admission:
    active: bool = True


class _AdmissionMiddleware:
    def __init__(self, app: ASGIApp, admission: _Admission) -> None:
        self.app = app
        self.admission = admission

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self.admission.active:
            await JSONResponse(
                {"detail": "Test runtime is closed"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


@contextmanager
def owned_test_runtime(
    config: TestRuntimeConfig, provider: OIDCProvider
) -> Iterator[RuntimeBundle]:
    """Validate before I/O, assemble existing APIs, then revoke and dispose in reverse.

    Authentication is private to Foundation. The two runtime pools have the same
    SQL authority but distinct ownership. No migrations, identities, source grants,
    listener, worker or broker connection are created here.
    """
    if type(config) is not TestRuntimeConfig:
        raise ValueError("Trusted Python test runtime configuration required")
    # Revalidate even frozen instances: Settings.model_copy/model_construct bypass
    # normal validation, and trusted Python can replace dataclass attributes.
    validated = TestRuntimeConfig(
        settings=config.settings,
        runtime_database_url=config.runtime_database_url,
        authentication_database_url=config.authentication_database_url,
    )
    if type(provider) is not OIDCProvider or provider.test_only is not True:
        raise ValueError("Explicit test-only OIDC provider required")

    stack = ExitStack()
    admission = _Admission()
    cleanup_failed = False
    primary_error: BaseException | None = None

    def dispose(database: Database | AuthenticationDatabase) -> None:
        nonlocal cleanup_failed
        try:
            database.engine.dispose()
        except BaseException:
            # Do not let one failing disposal skip another or disclose its URL.
            cleanup_failed = True

    try:
        try:
            api_database = Database(validated.runtime_database_url)
            stack.callback(dispose, api_database)
            authentication = AuthenticationDatabase(validated.authentication_database_url)
            stack.callback(dispose, authentication)
            publisher_database = Database(validated.runtime_database_url)
            stack.callback(dispose, publisher_database)
            foundation = Foundation(api_database, provider, authentication)
            app = create_app(validated.settings, foundation)
            app.add_middleware(_AdmissionMiddleware, admission=admission)
            bundle = RuntimeBundle(app, api_database, publisher_database)
        except Exception:
            raise RuntimeAssemblyError("Test runtime assembly failed") from None
        yield bundle
    except BaseException as error:
        primary_error = error
        raise
    finally:
        admission.active = False
        stack.close()
        if cleanup_failed:
            if primary_error is not None:
                try:
                    BaseException.add_note(
                        primary_error, "One or more owned test runtime pools failed to dispose"
                    )
                except Exception:
                    # A caller exception can have malformed __notes__. Reporting
                    # cleanup must never replace that genuine body exception.
                    pass
            else:
                raise RuntimeCleanupError("Test runtime cleanup failed") from None
