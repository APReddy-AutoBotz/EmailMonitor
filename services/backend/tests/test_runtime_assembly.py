"""Pure ownership/admission regressions; actual SQL and operator proof is separate."""

import traceback
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, field, replace
from typing import Any, cast

import pytest
from api_client import APIClient
from emailmonitor.api import Capabilities, create_app
from emailmonitor.api import app as metadata_app
from emailmonitor.config import Settings
from emailmonitor.identity.foundation import Foundation
from emailmonitor.identity.oidc import OIDCProvider
from emailmonitor.organizations.database import AuthenticationDatabase, Database
from emailmonitor.runtime import (
    RuntimeAssemblyError,
    RuntimeBundle,
    RuntimeCleanupError,
    assembly,
    owned_test_runtime,
)
from emailmonitor.runtime import TestRuntimeConfig as RuntimeConfig
from fastapi import FastAPI

SECRET = "runtime-secret-sentinel"
RUNTIME_URL = f"postgresql+pg8000://runtime:{SECRET}@127.0.0.1:5432/disposable"
AUTH_URL = f"postgresql+pg8000://auth:auth-{SECRET}@127.0.0.1:5432/disposable"
ORIGIN = "https://app.example.test"


class NoExchange:
    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        raise AssertionError("Pure composition must not exchange identity tokens")


@pytest.fixture
def provider() -> OIDCProvider:
    return OIDCProvider(
        issuer="https://identity.example.test",
        client_id="synthetic-runtime",
        authorization_endpoint="https://identity.example.test/authorize",
        redirect_uri=ORIGIN + "/api/v1/auth/callback",
        verification_keys={"fixture": SECRET},
        exchange_adapter=NoExchange(),
        test_only=True,
    )


def configuration(**changes: Any) -> RuntimeConfig:
    values = {
        "settings": Settings(environment="test", fixture_mode=True, identity_stub=True),
        "runtime_database_url": RUNTIME_URL,
        "authentication_database_url": AUTH_URL,
        **changes,
    }
    return RuntimeConfig(**values)


@dataclass
class FakeEngine:
    name: str
    events: list[str]
    fail_cleanup: set[str]
    before_dispose: Callable[[], None] = lambda: None
    pool: object = field(default_factory=object)
    connection_attempts: int = 0

    def dispose(self) -> None:
        self.events.append("dispose:" + self.name)
        self.before_dispose()
        if self.name in self.fail_cleanup:
            raise RuntimeError(SECRET)

    def connect(self) -> None:
        self.connection_attempts += 1
        raise AssertionError("Pure runtime attempted a database connection")


@dataclass
class FakeDatabase:
    engine: FakeEngine

    def transaction(self) -> None:
        self.engine.connect()


@dataclass
class Pools:
    events: list[str] = field(default_factory=list)
    values: list[FakeDatabase] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    fail_construction: str | None = None
    fail_cleanup: set[str] = field(default_factory=set)
    runtime_calls: int = 0

    def _construct(self, name: str, url: str) -> FakeDatabase:
        self.events.append("construct:" + name)
        self.urls.append(url)
        if name == self.fail_construction:
            raise RuntimeError(SECRET)
        result = FakeDatabase(FakeEngine(name, self.events, self.fail_cleanup))
        self.values.append(result)
        return result

    def runtime(self, url: str) -> Database:
        name = "api" if self.runtime_calls == 0 else "publisher"
        self.runtime_calls += 1
        return cast(Database, self._construct(name, url))

    def authentication(self, url: str) -> AuthenticationDatabase:
        return cast(AuthenticationDatabase, self._construct("authentication", url))


@pytest.fixture
def pools(monkeypatch: pytest.MonkeyPatch) -> Pools:
    result = Pools()
    monkeypatch.setattr(assembly, "Database", result.runtime)
    monkeypatch.setattr(assembly, "AuthenticationDatabase", result.authentication)
    return result


def sanitized(error: BaseException) -> None:
    assert SECRET not in str(error)
    assert SECRET not in repr(error)
    assert SECRET not in "".join(traceback.format_exception(error))
    assert "postgresql" not in str(error)


def test_configuration_requires_explicit_inputs_and_is_frozen_redacted() -> None:
    with pytest.raises(TypeError):
        RuntimeConfig(**{})
    config = configuration()
    assert repr(config) == "TestRuntimeConfig()"
    with pytest.raises(FrozenInstanceError):
        cast(Any, config).runtime_database_url = AUTH_URL
    assert not hasattr(config, "from_environment")
    assert not hasattr(config, "model_validate_json")
    assert not hasattr(config, "provider")


@pytest.mark.parametrize(
    "settings",
    [
        Settings(),
        Settings(environment="development"),
        Settings(environment="test"),
        Settings(environment="test", fixture_mode=True),
        Settings(environment="test", identity_stub=True),
        {"environment": "test", "fixture_mode": True, "identity_stub": True},
        None,
    ],
)
def test_unsafe_or_implicit_settings_fail_without_io(settings: object, pools: Pools) -> None:
    with pytest.raises(ValueError) as caught:
        configuration(settings=settings)
    sanitized(caught.value)
    assert pools.events == []


@pytest.mark.parametrize(
    "field",
    [
        "live_sources_enabled",
        "outbound_email_enabled",
        "external_ai_enabled",
        "wider_web_enabled",
        "ocr_enabled",
        "environment",
        "fixture_mode",
        "identity_stub",
    ],
)
@pytest.mark.parametrize("bypass", ["model_copy", "model_construct"])
def test_pydantic_bypass_is_revalidated_before_io(field: str, bypass: str, pools: Pools) -> None:
    original = configuration().settings
    values = {field: SECRET if field == "environment" else True}
    if field in {"fixture_mode", "identity_stub"}:
        values[field] = "true"
    invalid = (
        original.model_copy(update=values)
        if bypass == "model_copy"
        else Settings.model_construct(**{**original.model_dump(), **values})
    )
    with pytest.raises(ValueError) as caught:
        configuration(settings=invalid)
    sanitized(caught.value)
    assert pools.events == []


def test_context_revalidates_config_before_io(pools: Pools, provider: OIDCProvider) -> None:
    config = configuration()
    object.__setattr__(
        config, "settings", config.settings.model_copy(update={"fixture_mode": False})
    )
    with pytest.raises(ValueError), owned_test_runtime(config, provider):
        pytest.fail("Invalid settings reached runtime body")
    assert pools.events == []


@pytest.mark.parametrize("field", ["fixture_mode", "identity_stub", "environment"])
def test_invalid_settings_cannot_leak_through_serializer_warnings(
    field: str, pools: Pools, recwarn: pytest.WarningsRecorder, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = configuration().settings.model_copy(update={field: SECRET})
    with pytest.raises(ValueError) as caught:
        configuration(settings=invalid)
    sanitized(caught.value)
    assert not recwarn.list
    assert capsys.readouterr() == ("", "")
    assert pools.events == []


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "sqlite:///disposable",
        RUNTIME_URL.replace("postgresql+pg8000", "postgresql"),
        RUNTIME_URL.replace("127.0.0.1", "localhost"),
        RUNTIME_URL.replace("127.0.0.1", "example.test"),
        RUNTIME_URL.replace("127.0.0.1", "[::1]"),
        RUNTIME_URL.replace("127.0.0.1", "127.1"),
        RUNTIME_URL.replace(":5432", ""),
        RUNTIME_URL.replace(":5432", ":0"),
        RUNTIME_URL.replace(":5432", ":65536"),
        RUNTIME_URL.replace(":5432", ":not-a-port"),
        RUNTIME_URL.replace("/disposable", ""),
        RUNTIME_URL.replace("/disposable", "/"),
        RUNTIME_URL.replace("/disposable", "/disposable/other"),
        RUNTIME_URL.replace(f"runtime:{SECRET}@", ""),
        RUNTIME_URL.replace(f":{SECRET}@", "@"),
        RUNTIME_URL.replace(f":{SECRET}@", ":@"),
        RUNTIME_URL + "?host=example.test",
        RUNTIME_URL + "?",
        RUNTIME_URL + "#fragment",
        RUNTIME_URL + "#",
        " " + RUNTIME_URL,
        RUNTIME_URL + "\n",
        None,
    ],
)
@pytest.mark.parametrize("field", ["runtime_database_url", "authentication_database_url"])
def test_url_refusals_are_redacted_and_precede_io(field: str, url: object, pools: Pools) -> None:
    with pytest.raises(ValueError) as caught:
        configuration(**{field: url})
    sanitized(caught.value)
    assert pools.events == []


@pytest.mark.parametrize(
    "url",
    [
        AUTH_URL.replace(":5432", ":5433"),
        AUTH_URL.replace("/disposable", "/different"),
        AUTH_URL.replace("//auth:", "//runtime:"),
        AUTH_URL.replace("//auth:", "//%72untime:"),
    ],
)
def test_urls_require_same_target_and_distinct_logins(url: str, pools: Pools) -> None:
    with pytest.raises(ValueError) as caught:
        configuration(authentication_database_url=url)
    sanitized(caught.value)
    assert pools.events == []


@pytest.mark.parametrize(
    "field", ["provider", "provider_import", "executor_factory", "broker_url", "production_enabled"]
)
def test_unknown_activation_inputs_are_rejected(field: str, pools: Pools) -> None:
    with pytest.raises(TypeError) as caught:
        configuration(**{field: SECRET})
    sanitized(caught.value)
    assert pools.events == []


@pytest.mark.parametrize("config", [None, {}, "untrusted.module:config"])
def test_only_python_config_is_accepted(
    config: object, provider: OIDCProvider, pools: Pools
) -> None:
    with pytest.raises(ValueError), owned_test_runtime(cast(RuntimeConfig, config), provider):
        pytest.fail("Untrusted selector reached runtime body")
    assert pools.events == []


@pytest.mark.parametrize("kind", ["false", "truthy", "mapping", "import", "missing"])
def test_only_explicit_test_provider_is_accepted(
    kind: str, provider: OIDCProvider, pools: Pools
) -> None:
    invalid: object = {
        "false": replace(provider, test_only=False),
        "truthy": replace(provider, test_only=cast(bool, "true")),
        "mapping": {"test_only": True},
        "import": "untrusted.module:provider",
        "missing": None,
    }[kind]
    with (
        pytest.raises(ValueError),
        owned_test_runtime(configuration(), cast(OIDCProvider, invalid)),
    ):
        pytest.fail("Non-test provider reached runtime body")
    assert pools.events == []


def test_owns_independent_pools_and_uses_existing_assembly(
    pools: Pools, provider: OIDCProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    foundations: list[Foundation] = []
    config = configuration()

    def assemble(settings: Settings, foundation: Foundation) -> FastAPI:
        foundations.append(foundation)
        assert settings == config.settings and settings is not config.settings
        return create_app(settings, foundation)

    def no_environment(*args: object) -> None:
        pytest.fail("Explicit composition read environment settings")

    monkeypatch.setattr(assembly, "create_app", assemble)
    monkeypatch.setattr(Settings, "from_environment", no_environment)
    with owned_test_runtime(config, provider) as bundle:
        assert isinstance(bundle, RuntimeBundle)
        assert repr(bundle) == "RuntimeBundle()"
        assert bundle.api_database is cast(object, pools.values[0])
        assert bundle.publisher_database is cast(object, pools.values[2])
        assert foundations[0].database is bundle.api_database
        assert foundations[0].authentication is cast(object, pools.values[1])
        assert foundations[0].provider is provider
        assert len({id(database.engine.pool) for database in pools.values}) == 3
        assert pools.urls == [RUNTIME_URL, AUTH_URL, RUNTIME_URL]
        assert pools.events == ["construct:api", "construct:authentication", "construct:publisher"]
        assert not hasattr(bundle, "authentication")
        assert not hasattr(bundle, "worker")
        assert not hasattr(bundle, "broker")
        with pytest.raises(FrozenInstanceError):
            cast(Any, bundle).app = metadata_app
        with APIClient(bundle.app, ORIGIN) as client:
            assert client.get("/healthz").json() == {"status": "ok"}
            capabilities = client.get("/api/v1/capabilities").json()
            assert capabilities["tenant_data_api_available"] is True
            assert capabilities["live_sources_enabled"] is False
            assert capabilities["extraction_implemented"] is False
    assert pools.events[-3:] == ["dispose:publisher", "dispose:authentication", "dispose:api"]


@pytest.mark.parametrize(
    "failure", ["api", "authentication", "publisher", "foundation", "app", "gate", "bundle"]
)
def test_partial_assembly_failure_disposes_every_acquired_pool_in_reverse(
    failure: str, pools: Pools, provider: OIDCProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError(SECRET)

    if failure in {"api", "authentication", "publisher"}:
        pools.fail_construction = failure
    elif failure == "foundation":
        monkeypatch.setattr(assembly, "Foundation", fail)
    elif failure == "app":
        monkeypatch.setattr(assembly, "create_app", fail)
    elif failure == "bundle":
        monkeypatch.setattr(assembly, "RuntimeBundle", fail)
    else:
        monkeypatch.setattr(FastAPI, "add_middleware", fail)
    with (
        pytest.raises(RuntimeAssemblyError) as caught,
        owned_test_runtime(configuration(), provider),
    ):
        pytest.fail("Failed assembly reached runtime body")
    sanitized(caught.value)
    assert str(caught.value) == "Test runtime assembly failed"
    assert [event for event in pools.events if event.startswith("dispose:")] == [
        "dispose:" + database.engine.name for database in reversed(pools.values)
    ]


@pytest.mark.parametrize(
    "failures", [{"api"}, {"authentication"}, {"publisher"}, {"api", "authentication", "publisher"}]
)
def test_cleanup_failures_attempt_all_pools_and_do_not_leak(
    failures: set[str], pools: Pools, provider: OIDCProvider
) -> None:
    pools.fail_cleanup.update(failures)
    with (
        pytest.raises(RuntimeCleanupError) as caught,
        owned_test_runtime(configuration(), provider),
    ):
        pass
    sanitized(caught.value)
    assert str(caught.value) == "Test runtime cleanup failed"
    assert pools.events[-3:] == ["dispose:publisher", "dispose:authentication", "dispose:api"]


def test_body_with_malformed_notes_is_preserved_on_cleanup_failure(
    pools: Pools, provider: OIDCProvider
) -> None:
    pools.fail_cleanup.add("publisher")
    failure = RuntimeError("Original caller failure")
    cast(Any, failure).__notes__ = 1
    with pytest.raises(RuntimeError) as caught, owned_test_runtime(configuration(), provider):
        raise failure
    assert caught.value is failure
    assert pools.events[-3:] == ["dispose:publisher", "dispose:authentication", "dispose:api"]


@pytest.mark.parametrize("cleanup_failure", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt, GeneratorExit])
def test_body_exception_is_preserved_and_all_cleanup_is_attempted(
    cleanup_failure: bool,
    error_type: type[BaseException],
    pools: Pools,
    provider: OIDCProvider,
) -> None:
    if cleanup_failure:
        pools.fail_cleanup.update({"api", "authentication", "publisher"})
    failure = error_type("Original caller failure")
    with pytest.raises(error_type) as caught, owned_test_runtime(configuration(), provider):
        raise failure
    assert caught.value is failure
    assert str(caught.value) == "Original caller failure"
    if cleanup_failure:
        assert caught.value.__notes__ == ["One or more owned test runtime pools failed to dispose"]
    assert pools.events[-3:] == ["dispose:publisher", "dispose:authentication", "dispose:api"]


def test_construction_failure_remains_primary_when_cleanup_also_fails(
    pools: Pools, provider: OIDCProvider
) -> None:
    pools.fail_construction = "publisher"
    pools.fail_cleanup.update({"api", "authentication"})
    with (
        pytest.raises(RuntimeAssemblyError) as caught,
        owned_test_runtime(configuration(), provider),
    ):
        pytest.fail("Failed construction reached runtime body")
    sanitized(caught.value)
    assert caught.value.__notes__ == ["One or more owned test runtime pools failed to dispose"]
    assert pools.events[-2:] == ["dispose:authentication", "dispose:api"]


@pytest.mark.parametrize("start_before_close", [False, True])
@pytest.mark.parametrize("failure", ["none", "body", "cleanup"])
def test_retained_app_refuses_http_before_disposal_without_database_access(
    start_before_close: bool, failure: str, pools: Pools, provider: OIDCProvider
) -> None:
    if failure == "cleanup":
        pools.fail_cleanup.add("publisher")
    requests: list[int] = []

    def assert_closed() -> None:
        response = client.get("/api/v1/auth/start")
        requests.append(response.status_code)
        assert response.status_code == 503

    try:
        with owned_test_runtime(configuration(), provider) as bundle:
            client = APIClient(bundle.app, ORIGIN)
            if start_before_close:
                assert client.get("/healthz").status_code == 200
            for database in pools.values:
                database.engine.before_dispose = assert_closed
            if failure == "body":
                raise LookupError("Caller failed")
    except LookupError:
        assert failure == "body"
    except RuntimeCleanupError:
        assert failure == "cleanup"
    for path in ("/healthz", "/api/v1/auth/start", "/api/v1/me", "/openapi.json", "/unknown"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Test runtime is closed"}
        assert response.headers["Cache-Control"] == "no-store"
    assert client.post("/api/v1/auth/logout").status_code == 503
    assert requests == [503, 503, 503]
    assert all(database.engine.connection_attempts == 0 for database in pools.values)


def test_metadata_default_remains_unwired_after_owned_runtime(
    pools: Pools, provider: OIDCProvider
) -> None:
    with owned_test_runtime(configuration(), provider):
        pass
    with APIClient(metadata_app, ORIGIN) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/v1/capabilities").json() == Capabilities().model_dump()
        assert set(client.get("/openapi.json").json()["paths"]) == {
            "/healthz",
            "/api/v1/capabilities",
        }
        assert client.get("/api/v1/auth/start").status_code == 404


def test_closing_one_runtime_does_not_revoke_another(pools: Pools, provider: OIDCProvider) -> None:
    with owned_test_runtime(configuration(), provider) as first:
        first_client = APIClient(first.app, ORIGIN)
        with owned_test_runtime(configuration(), provider) as second:
            second_client = APIClient(second.app, ORIGIN)
            assert first_client.get("/healthz").status_code == 200
            assert second_client.get("/healthz").status_code == 200
            assert first.api_database is not second.api_database
            assert first.publisher_database is not second.publisher_database
            assert len({id(database.engine.pool) for database in pools.values}) == 6
        assert second_client.get("/healthz").status_code == 503
        assert first_client.get("/healthz").status_code == 200
    assert first_client.get("/healthz").status_code == 503
    assert len([event for event in pools.events if event.startswith("dispose:")]) == 6
