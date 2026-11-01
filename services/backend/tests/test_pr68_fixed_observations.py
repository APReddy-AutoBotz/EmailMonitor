"""Synthetic diagnostics: no browser, database, broker, or external access."""

import asyncio
import contextlib
import contextvars
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import operator_ui_acceptance as guest
import pytest
import test_installed_operator_acceptance as installed
import test_installed_xml_acceptance as xml
from emailmonitor.runtime import entrypoint, service_publisher
from emailmonitor.runtime.publisher import PublisherError
from playwright._impl._connection import Channel as PlaywrightChannel
from playwright._impl._connection import Connection


@pytest.mark.parametrize("at_limit", [False, True])
def test_event_error_preserves_exact_refusal_bit(at_limit: bool) -> None:
    async def run() -> None:
        channel = guest.Channel()
        if at_limit:
            channel.identifier = 512
            with pytest.raises(
                RuntimeError, match="^UI diagnostic request cap exceeded$"
            ) as caught:
                await channel.request({"kind": "control"})
            original = caught.value
        else:
            original = RuntimeError("private unrelated error")

        class ConnectionDouble:
            _on_event_listener_error = Connection._on_event_listener_error
            wrap_api_call = Connection.wrap_api_call

            def __init__(self) -> None:
                self._loop = asyncio.get_running_loop()
                self._api_zone = contextvars.ContextVar("test_zone", default=None)
                self._error = None

        connection = cast(Any, ConnectionDouble())
        transport = PlaywrightChannel(connection, cast(Any, SimpleNamespace(_guid="synthetic")))
        with contextlib.redirect_stderr(io.StringIO()):
            connection._on_event_listener_error(original)
        with pytest.raises(RuntimeError) as reraised:
            await transport.send("expect", None, {})
        assert reraised.value.__cause__ is None
        receiver = asyncio.current_task()
        assert receiver is not None
        capture = guest.BrowserFailureCapture(receiver, channel)
        capture.record(reraised.value)
        result = capture.result(reraised.value)
        assert result is not None and result.request_limit_refused is at_limit
        assert channel.identifier == (512 if at_limit else 0)

    asyncio.run(run())


def test_after_admission_refusal_preserves_capacity() -> None:
    async def run() -> None:
        channel = guest.Channel()

        class ControlledCapacity:
            async def acquire(self) -> None:
                channel.identifier = 512

            def release(self) -> None:
                pass

        channel.capacity = cast(Any, ControlledCapacity())
        with pytest.raises(RuntimeError, match="^UI diagnostic request cap exceeded$"):
            await channel.request({"kind": "control"})
        assert channel.request_limit_refused and channel.admitted == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "stage",
    [
        "startup",
        "pending",
        "broker_connect",
        "claim",
        "broker_send",
        "confirm",
        "cleanup",
        "private\ninjected=1",
    ],
)
def test_installed_finite_stage_is_closed_and_suppressed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    stderr = f"service_publisher_stage={stage}\nservice_runtime_failed\n".encode()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, b"", stderr)
    )
    with pytest.raises(RuntimeError, match="^Installed finite service command failed$") as caught:
        installed.finite(tmp_path, "publish-once", tmp_path / "private", publisher_diagnostics=True)
    output = tmp_path / "out"
    installed.report_publisher_failure(caught.value, output)
    text = output.read_text()
    assert text.startswith("installed_publisher_failure=exit_nonzero\n")
    assert getattr(caught.value, "_em_publisher_stage", None) == (
        stage if "private" not in stage else None
    )
    assert "private" not in text and "injected" not in text


@pytest.mark.parametrize(
    ("observed", "stage", "expected"),
    [
        (True, "confirm", "confirm"),
        (False, "confirm", "unavailable"),
        (True, "private", "unavailable"),
    ],
)
def test_xml_order_is_first_observation_only(
    tmp_path: Path, observed: bool, stage: str, expected: str
) -> None:
    output = tmp_path / "out"
    xml.report_publisher_order(observed, stage, output)
    xml.report_publisher_order(not observed, "claim", output)
    text = output.read_text()
    assert text.count("installed_xml_publisher_order=") == 1
    assert text.endswith("installed_xml_publisher_stage=" + expected + "\n")
    assert "private" not in text


@pytest.mark.parametrize("enabled", [False, True])
def test_entrypoint_stage_is_opt_in_and_keeps_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    enabled: bool,
) -> None:
    path = tmp_path / "config"
    path.write_text("{}")
    monkeypatch.setattr(entrypoint, "load_config", lambda _: object())
    error = PublisherError("private")
    cast(Any, error)._em_publisher_stage = "confirm"
    monkeypatch.setattr(service_publisher, "publish_service_once", Mock(side_effect=error))
    monkeypatch.setattr(sys, "argv", ["service", "publish-once", "--config", str(path)])
    if enabled:
        monkeypatch.setenv("EM_SYNTHETIC_PUBLISHER_STAGE", "1")
    else:
        monkeypatch.delenv("EM_SYNTHETIC_PUBLISHER_STAGE", raising=False)
    assert entrypoint.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        captured.err
        == ("service_publisher_stage=confirm\n" if enabled else "") + "service_runtime_failed\n"
    )
    assert "private" not in captured.err


@pytest.mark.parametrize(
    "stage", ["pending", "broker_connect", "claim", "broker_send", "confirm", "cleanup"]
)
def test_real_service_publisher_reports_only_fixed_failure_phase(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from unittest.mock import MagicMock
    from uuid import uuid4

    from emailmonitor.runtime.publisher import PublisherCleanupError

    organization, resource, event, item = uuid4(), uuid4(), uuid4(), uuid4()
    config = SimpleNamespace(
        process=SimpleNamespace(kind="publisher", principal=uuid4(), pass_limit=1),
        organization=organization,
        database_url="synthetic",
        broker_url="fixture",
        queue="fixture",
    )
    database = MagicMock(organization=organization)
    pending = database.engine.begin.return_value.__enter__.return_value
    pending.execute.return_value.mappings.return_value.all.return_value = [
        {
            "organization_id": organization,
            "resource_id": resource,
            "purpose": "extraction",
            "generation": 1,
            "event_id": event,
            "item_id": item,
        }
    ]
    transaction = MagicMock()
    database.tenant.return_value.__enter__.return_value = (transaction, object())
    transaction.execute.return_value.scalar_one.return_value = "fixture_io"
    application, connection = MagicMock(), MagicMock()
    monkeypatch.setattr(service_publisher, "ServiceDatabase", lambda *args: database)
    monkeypatch.setattr(service_publisher, "broker_application", lambda *args: application)
    monkeypatch.setattr(service_publisher, "Connection", lambda *args, **kwargs: connection)
    monkeypatch.setattr(service_publisher, "Producer", lambda *args: object())
    monkeypatch.setattr(service_publisher, "phase_queue", lambda *args: "fixture")
    failure = RuntimeError("private sentinel")
    if stage == "pending":
        pending.execute.side_effect = failure
    elif stage == "broker_connect":
        connection.ensure_connection.side_effect = failure
    elif stage == "claim":
        transaction.execute.side_effect = failure
    elif stage == "broker_send":
        application.send_task.side_effect = failure
    elif stage == "confirm":
        transaction.execute.side_effect = [
            SimpleNamespace(scalar_one=lambda: "fixture_io"),
            failure,
        ]
    else:
        application.close.side_effect = failure
    expected = PublisherCleanupError if stage == "cleanup" else PublisherError
    with pytest.raises(expected) as caught:
        service_publisher.publish_service_once(cast(Any, config))
    assert cast(Any, caught.value)._em_publisher_stage == stage
    assert "private" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("failure", ["authority", "invalid_phase"])
def test_claim_stage_does_not_identify_underlying_failure(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Two distinct synthetic failures reach the same sanitized claim receipt."""
    from unittest.mock import MagicMock
    from uuid import uuid4

    from emailmonitor.organizations.database import AuthorizationDenied

    organization = uuid4()
    config = SimpleNamespace(
        process=SimpleNamespace(kind="publisher", principal=uuid4(), pass_limit=1),
        organization=organization,
        database_url="synthetic",
        broker_url="fixture",
        queue="fixture",
    )
    database = MagicMock(organization=organization)
    pending = database.engine.begin.return_value.__enter__.return_value
    pending.execute.return_value.mappings.return_value.all.return_value = [
        {
            "organization_id": organization,
            "resource_id": uuid4(),
            "purpose": "export",
            "generation": 1,
            "event_id": uuid4(),
            "item_id": None,
        }
    ]
    transaction = MagicMock()
    database.tenant.return_value.__enter__.return_value = (transaction, object())
    if failure == "authority":
        database.tenant.return_value.__enter__.side_effect = AuthorizationDenied()
    else:
        transaction.execute.return_value.scalar_one.return_value = "unsupported"
    application, connection = MagicMock(), MagicMock()
    monkeypatch.setattr(service_publisher, "ServiceDatabase", lambda *args: database)
    monkeypatch.setattr(service_publisher, "broker_application", lambda *args: application)
    monkeypatch.setattr(service_publisher, "Connection", lambda *args, **kwargs: connection)
    monkeypatch.setattr(service_publisher, "Producer", lambda *args: object())
    with pytest.raises(PublisherError, match="^Service publication failed$") as caught:
        service_publisher.publish_service_once(cast(Any, config))
    assert cast(Any, caught.value)._em_publisher_stage == "claim"
    assert caught.value.__cause__ is None
    application.send_task.assert_not_called()


@pytest.mark.parametrize("report_available", [False, True])
def test_xml_capture_cannot_replace_runner_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report_available: bool
) -> None:
    import threading

    original = RuntimeError("private runner failure")
    output = tmp_path / ("output" if report_available else "missing/output")
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    observed = threading.Event()
    observed.set()
    with pytest.raises(RuntimeError) as caught:
        with xml.capture_publisher_order(observed, lambda: "confirm"):
            raise original
    assert caught.value is original
    if report_available:
        assert output.read_text() == (
            "installed_xml_publisher_order=publisher_handler_observed\n"
            "installed_xml_publisher_stage=confirm\n"
        )


def test_xml_capture_success_emits_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import threading

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with xml.capture_publisher_order(threading.Event(), lambda: "private"):
        pass
    assert not output.exists()
