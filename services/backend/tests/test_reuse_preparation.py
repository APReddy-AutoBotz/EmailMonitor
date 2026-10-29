"""Owned synthetic preparation fakes; these do not exercise PostgreSQL or grants."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from test_associations import ORG, ORIGIN, SETTINGS
from test_job_contracts import request_body

from emailmonitor.associations.reuse_preparation import prepare_reuse
from emailmonitor.extraction.fixture import article_bytes
from emailmonitor.extraction.html import parse_article
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.database import AuthorizationDenied

SOURCE, TARGET, BATCH = UUID(int=2), UUID(int=3), UUID(int=4)
NOW = datetime(2026, 10, 2, tzinfo=UTC)
URL = ORIGIN + "article-a.html"


def setup(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, dict[str, object]]:
    observed = parse_article(SETTINGS, URL, article_bytes("article-a.html"))
    row: dict[str, object] = {
        "organization_id": ORG,
        "job_id": SOURCE,
        "article_url": URL,
        "revision": 1,
        "source_id": "synthetic-publisher",
        "policy_version": 1,
        "generation": 1,
        "deletion_generation": 1,
        "discovery_revision": 1,
        "source_digest": observed.acquisition_digest,
        "observation": observed.model_dump(mode="json"),
        "observed_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(days=1),
        "batch_expires_at": NOW + timedelta(days=1),
    }
    request = {
        **request_body(),
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"},
    }
    monkeypatch.setattr(Ledger, "_lock", lambda *_: {"request": request})
    service, connection = MagicMock(), MagicMock()
    service._lock = MagicMock()
    service.settings = SETTINGS
    service.extraction._scope.return_value = {
        "source_id": "synthetic-publisher",
        "policy_version": 1,
    }

    def execute(statement: object, *_: object) -> MagicMock:
        result = MagicMock()
        if "clock_timestamp()" in str(statement):
            result.scalar_one.return_value = NOW
        else:
            result.mappings.return_value.first.return_value = row.copy()
        return result

    connection.execute.side_effect = execute
    return connection, service, row


def test_prepares_distinct_unaccepted_draft_and_deterministic_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, service, row = setup(monkeypatch)
    first = prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)
    second = prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)
    assert first == second
    assert first.lineage.source_job_id == SOURCE and first.lineage.target_job_id == TARGET
    assert first.lineage.observed_at == row["observed_at"]
    assert first.bundle.associations[0].state == "needs_review"
    assert first.bundle.associations[0].revision == 1
    assert first.bundle.candidates[0].address.raw_address not in repr(first)
    assert URL not in repr(first)
    assert service._lock.call_count == 4
    assert service.extraction._scope.call_count == 4
    assert all(
        str(call.args[0]).lstrip().startswith("SELECT")
        for call in connection.execute.call_args_list
    )


@pytest.mark.parametrize(
    "kind", ["same_job", "wrong_tenant", "wrong_source", "stale", "expired", "url", "malformed"]
)
def test_invalid_source_does_not_prepare(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    connection, service, row = setup(monkeypatch)
    if kind == "same_job":
        row["job_id"] = TARGET
    elif kind == "wrong_tenant":
        row["organization_id"] = UUID(int=99)
    elif kind == "wrong_source":
        row["source_id"] = "other-source"
    elif kind == "stale":
        row["observed_at"] = NOW - timedelta(days=2)
    elif kind == "expired":
        row["expires_at"] = NOW
    elif kind == "url":
        row["observation"] = {**row["observation"], "url": ORIGIN + "article-b.html"}  # type: ignore[dict-item]
    else:
        row["observation"] = {"route": "html"}
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)


def test_refuses_when_explicit_target_choice_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service, _ = setup(monkeypatch)
    monkeypatch.setattr(Ledger, "_lock", lambda *_: {"request": request_body()})
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)
    service.extraction._scope.assert_not_called()
    connection.execute.assert_not_called()


def test_late_visibility_change_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service, row = setup(monkeypatch)
    original = connection.execute.side_effect
    reads = 0

    def execute(statement: object, *args: object) -> MagicMock:
        nonlocal reads
        result = original(statement, *args)
        if "clock_timestamp()" not in str(statement):
            reads += 1
            if reads == 2:
                result.mappings.return_value.first.return_value = {**row, "revision": 2}
        return result

    connection.execute.side_effect = execute
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)


def test_expiry_during_preparation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service, row = setup(monkeypatch)
    original = connection.execute.side_effect
    clocks = 0

    def execute(statement: object, *args: object) -> MagicMock:
        nonlocal clocks
        result = original(statement, *args)
        if "clock_timestamp()" in str(statement):
            clocks += 1
            if clocks == 2:
                result.scalar_one.return_value = row["expires_at"]
        return result

    connection.execute.side_effect = execute
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)


def test_policy_change_during_preparation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service, _ = setup(monkeypatch)
    service.extraction._scope.side_effect = [
        {"source_id": "synthetic-publisher", "policy_version": 1},
        {"source_id": "synthetic-publisher", "policy_version": 2},
    ]
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)


@pytest.mark.parametrize("route", ["pdf", "xml"])
def test_bound_source_documents_keep_original_job_binding(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    from test_pdf_extraction import parse as parse_pdf
    from test_xml_pipeline import retained as retained_xml

    from emailmonitor.extraction.pdf_retained import PdfBinding, retain_pdf

    connection, service, row = setup(monkeypatch)
    if route == "pdf":
        source = retain_pdf(
            parse_pdf("article-a.pdf"),
            PdfBinding(
                organization=ORG,
                job=SOURCE,
                item=UUID(int=3),
                generation=1,
                deletion_generation=1,
                policy_version=1,
                discovery_revision=1,
            ),
            permit_excerpts=True,
        )
        assert source.content_digest is not None
        row["source_digest"] = source.content_digest
    else:
        xml = retained_xml()
        source = xml.model_copy(
            update={"binding": xml.binding.model_copy(update={"organization": ORG})}
        )
        row["source_digest"] = source.acquisition_digest
    row["article_url"] = source.url
    row["observation"] = source.model_dump(mode="json")
    prepared = prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)
    assert prepared.lineage.source_job_id == SOURCE
    assert prepared.lineage.content_digest == source.content_digest
    assert all(a.state != "accepted" for a in prepared.bundle.associations)
    raw = source.model_dump(mode="json")
    raw["binding"]["job"] = str(UUID(int=77))
    row["observation"] = raw
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)
