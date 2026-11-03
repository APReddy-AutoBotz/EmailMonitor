"""Closed synthetic publisher diagnostics; no real service or data is used."""

import builtins
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import test_installed_operator_acceptance as installed
import test_installed_xml_acceptance as xml
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.runtime import entrypoint, service_publisher
from emailmonitor.runtime.claim_diagnostics import claim_receipt, valid_claim_receipt
from emailmonitor.runtime.database import ServiceDatabase
from emailmonitor.runtime.publisher import PublisherError
from sqlalchemy.exc import DBAPIError


def translated(code: object) -> AuthorizationDenied:
    """Match the real ServiceDatabase suppressed DBAPI translation."""
    try:
        raise DBAPIError("private SQL", {"secret": "private"}, Exception({"C": code}), False)
    except DBAPIError:
        try:
            raise AuthorizationDenied() from None
        except AuthorizationDenied as error:
            return error


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("55P03", "sql_55p03"),
        ("EM017", "sql_em017"),
        ("42501", "sql_42501"),
        ("57014", "sql_57014"),
        ("40P01", "sql_40p01"),
        ("40001", "sql_40001"),
        ("XX001", "db_other"),
        ("private\ninjected=1", "db_unknown"),
        (None, "db_unknown"),
    ],
)
def test_suppressed_db_failure_has_only_allowlisted_category(code: object, category: str) -> None:
    result = claim_receipt(translated(code), "claim_sql", "export")
    assert result == f"claim_sql.{category}.export"
    assert valid_claim_receipt(result)
    assert "private" not in result and "\n" not in result


def test_non_database_and_invalid_receipt_inputs_are_closed() -> None:
    assert claim_receipt(AuthorizationDenied("private"), "authority_or_cleanup", "export") == (
        "authority_or_cleanup.non_db.export"
    )
    assert claim_receipt(ValueError("private"), "phase_validation", "extraction") == (
        "phase_validation.non_db.extraction"
    )
    assert claim_receipt(translated("55P03"), "claim_sql", "extraction") == (
        "claim_sql.sql_55p03.extraction"
    )
    assert claim_receipt(ValueError(), "private", "export") is None
    assert claim_receipt(ValueError(), "claim_sql", "private") is None
    invalid: list[object] = [
        None,
        {},
        "claim_sql.private.export",
        "claim_sql.non_db.export\ninjected=1",
    ]
    for value in invalid:
        assert not valid_claim_receipt(value)


def test_classifier_failure_is_never_allowed_to_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: Any) -> None:
        raise RuntimeError("private diagnostic failure")

    monkeypatch.setattr("emailmonitor.runtime.claim_diagnostics.claim_receipt", fail)
    assert service_publisher._claim_receipt(ValueError("private"), "claim_sql", "export") is None


@pytest.mark.parametrize(
    ("operation", "code", "expected"),
    [
        ("authority_setup", "55P03", "authority_or_cleanup.sql_55p03.export"),
        ("authority_setup", "EM017", "authority_or_cleanup.sql_em017.export"),
        ("claim_sql", "55P03", "claim_sql.sql_55p03.export"),
        ("claim_sql", "42501", "claim_sql.sql_42501.export"),
        ("rollback_replacement", "55P03", "claim_sql.sql_55p03.export"),
        ("probe_failure", "55P03", None),
        ("phase_validation", None, "phase_validation.non_db.export"),
        ("queue_selection", None, "queue_selection.non_db.export"),
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_real_tenant_translation_and_publisher_remain_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    code: str | None,
    expected: str | None,
    enabled: bool,
) -> None:
    organization, principal = uuid4(), uuid4()
    process = SimpleNamespace(kind="publisher", principal=principal, pass_limit=1)
    config = SimpleNamespace(
        process=process,
        organization=organization,
        database_url="fixture",
        broker_url="fixture",
        queue="fixture",
    )
    database = object.__new__(ServiceDatabase)
    database.process = cast(Any, process)
    database.organization = organization
    database.engine = MagicMock()
    pending_context, tenant_context = MagicMock(), MagicMock()
    database.engine.begin.side_effect = [pending_context, tenant_context]
    pending = pending_context.__enter__.return_value
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
    connection = tenant_context.__enter__.return_value
    query_result, phase_result = MagicMock(), MagicMock()
    phase_result.scalar_one.return_value = (
        "unsupported" if operation == "phase_validation" else "export"
    )
    db_failure = DBAPIError("private SQL", {"secret": "private"}, Exception({"C": code}), False)
    if operation == "authority_setup":
        connection.execute.side_effect = [query_result, db_failure]
    elif operation in {"claim_sql", "rollback_replacement", "probe_failure"}:
        connection.execute.side_effect = [query_result, query_result, db_failure]
        if operation in {"rollback_replacement", "probe_failure"}:
            tenant_context.__exit__.side_effect = DBAPIError(
                "private rollback", {}, Exception({"C": "42501"}), False
            )
    else:
        connection.execute.side_effect = [query_result, query_result, phase_result]
    monkeypatch.setattr("emailmonitor.runtime.database.apply_work_binding", lambda *_: None)
    monkeypatch.setattr("emailmonitor.runtime.database.apply_fixture_binding", lambda *_: None)
    application, broker = MagicMock(), MagicMock()
    monkeypatch.setattr(service_publisher, "ServiceDatabase", lambda *_: database)
    monkeypatch.setattr(service_publisher, "broker_application", lambda _: application)
    monkeypatch.setattr(service_publisher, "Connection", lambda *_, **__: broker)
    monkeypatch.setattr(service_publisher, "Producer", lambda _: object())
    if operation == "queue_selection":
        monkeypatch.setattr(
            service_publisher, "phase_queue", MagicMock(side_effect=ValueError("private"))
        )
    probe = MagicMock(return_value=None)
    if operation == "probe_failure":
        monkeypatch.setattr(service_publisher, "_claim_receipt", probe)
    with pytest.raises(PublisherError, match="^Service publication failed$") as caught:
        service_publisher.publish_service_once(cast(Any, config), diagnostic=enabled)
    error = caught.value
    assert error.__cause__ is None and error.__suppress_context__
    assert cast(Any, error)._em_publisher_stage == "claim"
    assert getattr(error, "_em_publisher_claim", None) == (expected if enabled else None)
    assert "private" not in str(error)
    if operation == "probe_failure":
        assert probe.call_count == (1 if enabled else 0)
    application.send_task.assert_not_called()
    tenant_context.__exit__.assert_called_once()


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_receipt_is_opt_in_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    enabled: bool,
) -> None:
    path = tmp_path / "config"
    path.write_text("{}")
    monkeypatch.setattr(entrypoint, "load_config", lambda _: object())
    error = PublisherError("private")
    cast(Any, error)._em_publisher_stage = "claim"
    cast(Any, error)._em_publisher_claim = "claim_sql.sql_55p03.export"
    monkeypatch.setattr(service_publisher, "publish_service_once", MagicMock(side_effect=error))
    monkeypatch.setattr(sys, "argv", ["service", "publish-once", "--config", str(path)])
    if enabled:
        monkeypatch.setenv("EM_SYNTHETIC_PUBLISHER_STAGE", "1")
    else:
        monkeypatch.delenv("EM_SYNTHETIC_PUBLISHER_STAGE", raising=False)
    assert entrypoint.main() == 1
    result = capsys.readouterr()
    assert result.out == ""
    expected = (
        "service_publisher_stage=claim\nservice_publisher_claim=claim_sql.sql_55p03.export\n"
        if enabled
        else ""
    )
    assert result.err == expected + "service_runtime_failed\n"
    assert "private" not in result.err


@pytest.mark.parametrize("valid", [False, True])
def test_installed_parser_and_xml_receipt_are_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valid: bool
) -> None:
    claim = "claim_sql.sql_55p03.export" if valid else "claim_sql.private.export"
    stderr = (
        f"service_publisher_stage=claim\nservice_publisher_claim={claim}\nservice_runtime_failed\n"
    ).encode()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, b"", stderr)
    )
    with pytest.raises(RuntimeError, match="^Installed finite service command failed$") as caught:
        installed.finite(tmp_path, "publish-once", tmp_path / "config", publisher_diagnostics=True)
    error = caught.value
    assert getattr(error, "_em_publisher_claim", None) == (claim if valid else None)
    output = tmp_path / "out"
    xml.report_publisher_claim(error, output)
    xml.report_publisher_claim(RuntimeError("private later failure"), output)
    text = output.read_text()
    assert text.count("installed_xml_publisher_claim=") == 1
    assert text.endswith(
        "installed_xml_publisher_claim=" + (claim if valid else "unavailable") + "\n"
    )
    assert "private" not in text and "private" not in str(error)


def test_xml_claim_reserves_first_report_before_concurrent_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from emailmonitor.runtime import claim_diagnostics

    first, second = RuntimeError("private first"), RuntimeError("private second")
    cast(Any, first)._em_publisher_stage = cast(Any, second)._em_publisher_stage = "claim"
    cast(Any, first)._em_publisher_claim = "claim_sql.sql_55p03.export"
    cast(Any, second)._em_publisher_claim = "claim_sql.sql_em017.export"
    entered, release = threading.Event(), threading.Event()
    validate = claim_diagnostics.valid_claim_receipt

    def delayed(value: object) -> bool:
        entered.set()
        if not release.wait(timeout=2):
            raise RuntimeError("synthetic test deadline")
        return validate(value)

    monkeypatch.setattr(claim_diagnostics, "valid_claim_receipt", delayed)
    output = tmp_path / "out"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(xml.report_publisher_claim, first, output)
        try:
            assert entered.wait(timeout=2)
            xml.report_publisher_claim(second, output)
        finally:
            release.set()
        future.result(timeout=2)
    assert output.read_text() == "installed_xml_publisher_claim=claim_sql.sql_55p03.export\n"


def test_xml_failed_first_report_cannot_be_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "out"
    first = RuntimeError("private")
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", MagicMock(side_effect=OSError("private")))
        with pytest.raises(OSError):
            xml.report_publisher_claim(first, output)
    xml.report_publisher_claim(RuntimeError("later private"), output)
    assert not output.exists()


@pytest.mark.parametrize("failure", ["oversized", "import"])
def test_installed_diagnostic_failure_never_replaces_original_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    stderr = (
        b"service_publisher_stage=claim\n"
        b"service_publisher_claim=claim_sql.sql_55p03.export\nservice_runtime_failed\n"
    )
    if failure == "oversized":

        class NoDecode(bytes):
            def decode(self, *args: Any, **kwargs: Any) -> str:
                raise AssertionError("oversized stderr must not be decoded")

        stderr = NoDecode(stderr + b"private" * 200)
    original_import = builtins.__import__

    def checked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "emailmonitor.runtime.claim_diagnostics":
            raise RuntimeError("private diagnostic failure")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, b"", stderr)
    )
    with pytest.raises(RuntimeError, match="^Installed finite service command failed$") as caught:
        installed.finite(tmp_path, "publish-once", tmp_path / "config", publisher_diagnostics=True)
    assert getattr(caught.value, "_em_publisher_claim", None) is None
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    ("stage", "claim", "expected"),
    [
        ("claim", "claim_sql.sql_55p03.export", "claim_sql.sql_55p03.export"),
        ("claim", "authority_or_cleanup.sql_em017.export", "authority_or_cleanup.sql_em017.export"),
        ("claim", "phase_validation.non_db.extraction", "phase_validation.non_db.extraction"),
        ("claim", "claim_sql.private.export", "unavailable"),
        ("claim", "claim_sql.sql_55p03.export\ninjected=1", "unavailable"),
        ("confirm", "claim_sql.sql_55p03.export", "unavailable"),
        (None, {"private": "value"}, "unavailable"),
    ],
)
def test_reuse_claim_receipt_is_closed_and_preserves_first(
    tmp_path: Path, stage: object, claim: object, expected: str
) -> None:
    error = RuntimeError("private original")
    cast(Any, error)._em_publisher_stage = stage
    cast(Any, error)._em_publisher_claim = claim
    output = tmp_path / "output"
    installed.report_reuse_publisher_claim(error, output)
    installed.report_reuse_publisher_claim(RuntimeError("private later"), output)
    text = output.read_text()
    assert text == "reuse_publisher_claim=" + expected + "\n"
    assert "private" not in text and "injected" not in text


@pytest.mark.parametrize(
    ("enabled", "retained_reuse"), [(False, False), (False, True), (True, False), (True, True)]
)
def test_reuse_claim_reporting_is_opt_in_and_never_replaces_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: bool, retained_reuse: bool
) -> None:
    monkeypatch.setenv("EM_INSTALLED_STAGE_REPORT", "true" if enabled else "false")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    reporter = MagicMock(side_effect=OSError("private diagnostic"))
    monkeypatch.setattr(installed, "report_reuse_publisher_claim", reporter)
    original = RuntimeError("private original")
    try:
        raise original
    except RuntimeError as error:
        installed.report_reuse_claim_if_enabled(error, retained_reuse=retained_reuse)
        assert error is original
    assert reporter.call_count == int(enabled and retained_reuse)
    assert not (tmp_path / "output").exists()


def test_reuse_claim_reserves_first_before_concurrent_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from emailmonitor.runtime import claim_diagnostics

    first, second = RuntimeError("private first"), RuntimeError("private second")
    cast(Any, first)._em_publisher_stage = cast(Any, second)._em_publisher_stage = "claim"
    cast(Any, first)._em_publisher_claim = "claim_sql.sql_55p03.export"
    cast(Any, second)._em_publisher_claim = "claim_sql.sql_em017.export"
    entered, release = threading.Event(), threading.Event()
    validate = claim_diagnostics.valid_claim_receipt

    def delayed(value: object) -> bool:
        entered.set()
        if not release.wait(timeout=2):
            raise RuntimeError("synthetic test deadline")
        return validate(value)

    monkeypatch.setattr(claim_diagnostics, "valid_claim_receipt", delayed)
    output = tmp_path / "output"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(installed.report_reuse_publisher_claim, first, output)
        try:
            assert entered.wait(timeout=2)
            installed.report_reuse_publisher_claim(second, output)
        finally:
            release.set()
        future.result(timeout=2)
    assert output.read_text() == "reuse_publisher_claim=claim_sql.sql_55p03.export\n"


def test_reuse_claim_failed_first_report_cannot_be_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", MagicMock(side_effect=OSError("private")))
        with pytest.raises(OSError):
            installed.report_reuse_publisher_claim(RuntimeError("private first"), output)
    installed.report_reuse_publisher_claim(RuntimeError("private later"), output)
    assert not output.exists()
