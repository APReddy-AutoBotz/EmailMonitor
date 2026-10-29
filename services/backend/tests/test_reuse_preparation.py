"""Owned synthetic preparation fakes; these do not exercise PostgreSQL or grants."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from emailmonitor.associations.reuse_preparation import prepare_reuse
from emailmonitor.extraction.fixture import article_bytes
from emailmonitor.extraction.html import parse_article
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import canonical
from emailmonitor.organizations.database import AuthorizationDenied
from test_associations import ORG, ORIGIN, SETTINGS
from test_job_contracts import request_body

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
        "source_parent_job": None,
    }
    request = {
        **request_body(),
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"},
    }
    monkeypatch.setattr(
        Ledger,
        "_lock",
        lambda *_: {"request": {**request, "input": {"type": "url", "url": row["article_url"]}}},
    )
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
        elif "SELECT id FROM emailmonitor.execution_items" in str(statement):
            result.scalar_one_or_none.return_value = UUID(int=3)
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
    assert first.evidence.source_job == SOURCE and first.evidence.source_item is None
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
    "kind",
    ["same_job", "wrong_tenant", "wrong_source", "stale", "expired", "url", "malformed", "chain"],
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
    elif kind == "chain":
        row["source_parent_job"] = UUID(int=99)
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
        result = cast(MagicMock, original(statement, *args))
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
        result = cast(MagicMock, original(statement, *args))
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


@pytest.mark.parametrize("when", ["initial", "release"])
def test_source_authority_refusal_is_not_converted_to_reuse(
    monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    connection, service, _ = setup(monkeypatch)
    service._lock.side_effect = (
        AuthorizationDenied() if when == "initial" else [None, AuthorizationDenied()]
    )
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, URL, BATCH)
    assert all(
        str(call.args[0]).lstrip().startswith("SELECT")
        for call in connection.execute.call_args_list
    )


def test_no_contact_observation_stays_no_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, service, row = setup(monkeypatch)
    url = ORIGIN + "no-contact.html"
    source = parse_article(SETTINGS, url, article_bytes("no-contact.html"))
    row["article_url"] = url
    row["source_digest"] = source.acquisition_digest
    row["observation"] = source.model_dump(mode="json")
    result = prepare_reuse(connection, service, ORG, TARGET, url, BATCH)
    assert result.bundle.observation_status == "no_contact"
    assert result.bundle.candidates == () and result.bundle.associations == ()


@pytest.mark.parametrize("route", ["pdf", "xml"])
def test_bound_source_documents_keep_original_job_binding(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    from emailmonitor.extraction.pdf_retained import PdfBinding, RetainedPdf, retain_pdf
    from emailmonitor.extraction.xml_retained import RetainedXml
    from test_pdf_extraction import parse as parse_pdf
    from test_xml_pipeline import retained as retained_xml

    connection, service, row = setup(monkeypatch)
    source: RetainedPdf | RetainedXml
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
    assert prepared.evidence.source_job == SOURCE
    assert prepared.evidence.source_item == source.binding.item
    assert prepared.evidence.document == canonical(source.model_dump(mode="json"))
    assert all(a.state != "accepted" for a in prepared.bundle.associations)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    fence = [index for index, sql in enumerate(statements) if "execution_read_fence" in sql]
    reads = [
        index
        for index, sql in enumerate(statements)
        if "SELECT id FROM emailmonitor.execution_items" in sql
    ]
    assert len(fence) == 1 and len(reads) == 2 and fence[0] < reads[0] < reads[1]
    assert all("FOR SHARE" not in statements[index] for index in reads)
    raw = source.model_dump(mode="json")
    raw["binding"]["job"] = str(UUID(int=77))
    row["observation"] = raw
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)


def test_bound_source_execution_fence_refusal_stops_before_item_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emailmonitor.extraction.pdf_retained import PdfBinding, retain_pdf
    from test_pdf_extraction import parse as parse_pdf

    connection, service, row = setup(monkeypatch)
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
    row.update(
        article_url=source.url,
        source_digest=source.content_digest,
        observation=source.model_dump(mode="json"),
    )
    original = connection.execute.side_effect

    def execute(statement: object, *args: object) -> MagicMock:
        if "execution_read_fence" in str(statement):
            raise AuthorizationDenied()
        return cast(MagicMock, original(statement, *args))

    connection.execute.side_effect = execute
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)
    assert not any(
        "SELECT id FROM emailmonitor.execution_items" in str(call.args[0])
        for call in connection.execute.call_args_list
    )


@pytest.mark.parametrize("route", ["pdf", "xml"])
@pytest.mark.parametrize("failure", ["wrong_item", "missing_item", "late_item", "wrong_digest"])
def test_bound_source_requires_exact_completed_original_item(
    monkeypatch: pytest.MonkeyPatch, route: str, failure: str
) -> None:
    from emailmonitor.extraction.pdf_retained import PdfBinding, RetainedPdf, retain_pdf
    from emailmonitor.extraction.xml_retained import RetainedXml
    from test_pdf_extraction import parse as parse_pdf
    from test_xml_pipeline import retained as retained_xml

    connection, service, row = setup(monkeypatch)
    source: RetainedPdf | RetainedXml
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
        row["source_digest"] = source.content_digest
    else:
        xml = retained_xml()
        source = xml.model_copy(
            update={"binding": xml.binding.model_copy(update={"organization": ORG})}
        )
        row["source_digest"] = source.acquisition_digest
    row["article_url"] = source.url
    row["observation"] = source.model_dump(mode="json")
    if failure == "wrong_item":
        row["observation"]["binding"]["item"] = str(UUID(int=99))  # type: ignore[index]
    elif failure == "wrong_digest":
        row["source_digest"] = "a" * 64
    elif failure in {"missing_item", "late_item"}:
        original = connection.execute.side_effect
        seen = 0

        def execute(statement: object, *args: object) -> MagicMock:
            nonlocal seen
            result = cast(MagicMock, original(statement, *args))
            if "SELECT id FROM emailmonitor.execution_items" in str(statement):
                seen += 1
                if failure == "missing_item" or seen == 2:
                    result.scalar_one_or_none.return_value = None
            return result

        connection.execute.side_effect = execute
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)


def test_controlled_xml_keeps_and_checks_original_provider_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_provider_journey import registry, retained

    connection, service, row = setup(monkeypatch)
    original = retained(registry()[0])
    monkeypatch.setattr(
        "emailmonitor.associations.reuse_preparation.current_policy",
        lambda *_: {
            "version": 1,
            "support": {
                "provider_documents": [item.model_dump(mode="json") for item in registry()]
            },
        },
    )
    source = original.model_copy(
        update={"binding": original.binding.model_copy(update={"organization": ORG})}
    )
    row["article_url"] = source.url
    row["source_digest"] = source.acquisition_digest
    row["observation"] = source.model_dump(mode="json")
    prepared = prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)
    assert prepared.evidence.document == canonical(source.model_dump(mode="json"))
    document = source.model_dump(mode="json")
    assert isinstance(document["provider"], dict)
    document["provider"]["source_id"] = "different-source"
    row["observation"] = document
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)


@pytest.mark.parametrize("failure", ["different_digest", "missing", "wrong_version", "late_change"])
def test_controlled_xml_requires_current_registered_source(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from test_provider_journey import registry, retained

    connection, service, row = setup(monkeypatch)
    entries = registry()
    original = retained(entries[0])
    source = original.model_copy(
        update={"binding": original.binding.model_copy(update={"organization": ORG})}
    )
    row["article_url"] = source.url
    row["source_digest"] = source.acquisition_digest
    row["observation"] = source.model_dump(mode="json")
    reads = 0

    def policy(*_: object) -> dict[str, object]:
        nonlocal reads
        reads += 1
        documents = [item.model_dump(mode="json") for item in entries]
        if failure == "missing":
            documents = [documents[1]]
        if failure == "different_digest" or (failure == "late_change" and reads == 2):
            documents[0]["content_digest"] = "a" * 64
        return {
            "version": 2 if failure == "wrong_version" else 1,
            "support": {"provider_documents": documents},
        }

    monkeypatch.setattr("emailmonitor.associations.reuse_preparation.current_policy", policy)
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)


def test_partial_xml_remains_unavailable_without_fresh_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_xml_pipeline import retained

    connection, service, row = setup(monkeypatch)
    original = retained()
    source = original.model_copy(
        update={
            "binding": original.binding.model_copy(update={"organization": ORG}),
            "status": "partial",
            "reasons": ["unsupported_affiliation"],
        }
    )
    row["article_url"] = source.url
    row["source_digest"] = source.acquisition_digest
    row["observation"] = source.model_dump(mode="json")
    with pytest.raises(AuthorizationDenied):
        prepare_reuse(connection, service, ORG, TARGET, source.url, BATCH)
