"""Configuration extraction preserves validation, serialization and legacy imports."""

import hashlib
import json
import pickle
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, get_type_hints
from uuid import UUID

import pytest
from emailmonitor.runtime import assembly, publisher, worker
from emailmonitor.runtime.authority import ServiceProcess
from emailmonitor.runtime.service_config import ServiceRuntimeConfig
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Configuration validation must not open network connections")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def document(kind: str = "worker") -> dict[str, Any]:
    organization = UUID(int=11)
    return {
        "environment": "test",
        "database_url": "postgresql+pg8000://service:synthetic@127.0.0.1:5432/disposable",
        "broker_url": "pyamqp://service:synthetic@127.0.0.1:5672/disposable",
        "queue": "em-fixture-" + organization.hex,
        "organization": str(organization),
        "process": {"kind": kind, "principal": str(UUID(int=12))},
    }


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_schema_matches_pre_extraction_snapshot(
    mode: Literal["validation", "serialization"],
) -> None:
    # Captured from the original worker-defined class at source tree 272f4bef.
    schema = json.dumps(
        ServiceRuntimeConfig.model_json_schema(mode=mode), sort_keys=True, separators=(",", ":")
    ).encode()
    assert hashlib.sha256(schema).hexdigest() == (
        "aa744c5452b349530f06ca0a9567aa7f5fa265597499149c25fef9fc2916f031"
    )


@pytest.mark.parametrize("kind", ["worker", "publisher"])
@pytest.mark.parametrize(
    "profile", ["authored-html-service-reference", "controlled-xml-service-reference"]
)
def test_valid_model_defaults_serialization_and_same_class_reexport(
    kind: str, profile: str
) -> None:
    body = document(kind)
    body["profile"] = profile
    model = ServiceRuntimeConfig.model_validate_json(json.dumps(body))
    expected = {
        **{key: value for key, value in body.items() if key != "profile"},
        "process": {**body["process"], "pass_limit": 100},
        "lease_seconds": 30,
        "profile": profile,
    }
    assert worker.ServiceRuntimeConfig is ServiceRuntimeConfig
    assert type(model) is worker.ServiceRuntimeConfig
    assert model.model_dump(mode="json") == expected
    assert model.model_dump_json() == json.dumps(expected, separators=(",", ":"))
    assert worker.ServiceRuntimeConfig.model_validate(model.model_dump()) == model
    assert "database_url" not in repr(model) and "broker_url" not in repr(model)
    assert ServiceRuntimeConfig.model_config == {"extra": "forbid", "frozen": True, "strict": True}


@pytest.mark.parametrize("kind", ["worker", "publisher"])
def test_complete_configs_still_execute_existing_validators_in_order(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    body = document(kind)
    calls: list[str] = []
    original_database = assembly._database_target
    original_publisher = publisher.TestPublisherConfig

    def database(value: str) -> tuple[str, int, str, str]:
        assert value == body["database_url"]
        calls.append("database")
        return original_database(value)

    def broker(**kwargs: Any) -> publisher.TestPublisherConfig:
        assert kwargs == {name: body[name] for name in ("environment", "broker_url", "queue")}
        calls.append("broker")
        return original_publisher(**kwargs)

    monkeypatch.setattr(assembly, "_database_target", database)
    monkeypatch.setattr(publisher, "TestPublisherConfig", broker)
    ServiceRuntimeConfig.model_validate_json(json.dumps(body))
    assert calls == ["database", "broker"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment", "production"),
        ("environment", False),
        ("environment", "development"),
        ("queue", "em-fixture-foreign"),
        ("database_url", "postgresql+pg8000://service:synthetic@remote.example:5432/disposable"),
        ("broker_url", "pyamqp://service:synthetic@remote.example:5672/disposable"),
        ("lease_seconds", 0),
        ("lease_seconds", 121),
        ("lease_seconds", "30"),
        ("profile", "production"),
        ("unexpected", "value"),
        ("process", {"kind": "owner", "principal": str(UUID(int=12))}),
        ("process", {"kind": "worker", "principal": str(UUID(int=0))}),
        ("process", {"kind": "worker", "principal": str(UUID(int=12)), "pass_limit": 101}),
    ],
)
def test_complete_invalid_configs_still_refuse(field: str, value: object) -> None:
    body = {**document(), field: value}
    with pytest.raises(ValidationError) as caught:
        ServiceRuntimeConfig.model_validate_json(json.dumps(body))
    if field == "environment":
        assert any(
            error["loc"] == ("environment",) and error["type"] == "literal_error"
            for error in caught.value.errors()
        )


@pytest.mark.parametrize("failure", ["queue", "database", "broker"])
def test_validator_failure_stops_before_later_validation(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    body = document()
    if failure == "queue":
        body["queue"] = "em-fixture-foreign"
    calls: list[str] = []

    def database(value: str) -> tuple[str, int, str, str]:
        calls.append("database")
        if failure == "database":
            raise ValueError("synthetic database refusal")
        return "127.0.0.1", 5432, "disposable", "service"

    def broker(**kwargs: Any) -> publisher.TestPublisherConfig:
        calls.append("broker")
        raise ValueError("synthetic broker refusal")

    monkeypatch.setattr(assembly, "_database_target", database)
    monkeypatch.setattr(publisher, "TestPublisherConfig", broker)
    with pytest.raises(ValidationError):
        ServiceRuntimeConfig.model_validate_json(json.dumps(body))
    assert (
        calls == {"queue": [], "database": ["database"], "broker": ["database", "broker"]}[failure]
    )


def test_reflection_and_trusted_pickle_paths_resolve_the_same_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No runtime pickle transport is added. These are locally constructed bytes.
    # Existing pickles resolve the former module's explicit same-class re-export;
    # new pickles correctly identify the new module shipped in the same package.
    assert ServiceRuntimeConfig.__module__ == "emailmonitor.runtime.service_config"
    assert get_type_hints(ServiceRuntimeConfig)["process"] is ServiceProcess
    old_reference = b"cemailmonitor.runtime.worker\nServiceRuntimeConfig\n."
    assert pickle.loads(old_reference) is ServiceRuntimeConfig
    model = ServiceRuntimeConfig.model_validate_json(json.dumps(document()))
    restored = pickle.loads(pickle.dumps(model))
    assert type(restored) is ServiceRuntimeConfig and restored == model
    with monkeypatch.context() as legacy:
        legacy.setattr(ServiceRuntimeConfig, "__module__", "emailmonitor.runtime.worker")
        old_instance = pickle.dumps(model)
    restored = pickle.loads(old_instance)
    assert type(restored) is ServiceRuntimeConfig and restored == model


@pytest.mark.parametrize("kind", ["worker", "publisher"])
def test_fresh_valid_config_load_keeps_validation_and_single_read(
    tmp_path: Path, kind: str
) -> None:
    config = tmp_path / "synthetic-service.json"
    config.write_text(json.dumps(document(kind)))
    source = Path(__file__).resolve().parents[1] / "src"
    probe = """
import pathlib, socket, sys
sys.path.insert(0, sys.argv[1])
def denied(*args, **kwargs):
    raise AssertionError('No network allowed while validating service configuration')
socket.create_connection = denied
socket.getaddrinfo = denied
socket.socket.connect = denied
from emailmonitor.runtime import entrypoint
from emailmonitor.runtime.service_config import ServiceRuntimeConfig
assert 'emailmonitor.runtime.worker' not in sys.modules
assert 'emailmonitor.runtime.assembly' not in sys.modules
assert 'emailmonitor.runtime.publisher' not in sys.modules
config_path = pathlib.Path(sys.argv[2])
reads = []
original_open = pathlib.Path.open
def tracked_open(self, *args, **kwargs):
    if self == config_path:
        reads.append(args)
    return original_open(self, *args, **kwargs)
pathlib.Path.open = tracked_open
config = entrypoint.load_config(config_path)
assert reads == [('rb',)]
assert config.process.kind == sys.argv[3]
assert config.lease_seconds == 30
assert config.profile == 'authored-html-service-reference'
assert 'emailmonitor.runtime.assembly' in sys.modules
assert 'emailmonitor.runtime.publisher' in sys.modules
from emailmonitor.runtime import worker
assert worker.ServiceRuntimeConfig is ServiceRuntimeConfig
assert type(config) is worker.ServiceRuntimeConfig
assert ServiceRuntimeConfig.model_validate_json(config.model_dump_json()) == config
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe, str(source), str(config), kind],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
