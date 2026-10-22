"""Pure transaction composition checks; no actual SQL or transport proof."""

import ast
import hashlib
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.service import Extraction
from emailmonitor.extraction.xml_service import XmlExtraction
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.provider import ProviderJourney
from emailmonitor.sources import provider_documents as catalog
from test_provider_journey import registry


@pytest.mark.parametrize("kind", ["discover", "article"])
@pytest.mark.parametrize("failure", [None, "prepare", "authorize", "service_end", "commit"])
def test_request_one_fresh_transaction_preserves_checks_and_exit_failure(
    monkeypatch: pytest.MonkeyPatch, kind: str, failure: str | None
) -> None:
    events: list[str] = []
    connections: list[object] = []
    active: list[object] = []
    documents = registry()
    org, job = UUID(int=1), UUID(int=2)
    url = catalog.SEARCH_URL if kind == "discover" else catalog.DOI_URL
    work: Any = SimpleNamespace(
        kind=kind, url=url, lease=SimpleNamespace(organization=org, job=job)
    )
    row: dict[str, object] = {
        "plan": {"effective_query": catalog.QUERY},
        "source_id": catalog.SOURCE,
        "policy_version": 1,
        "revision": 1,
    }
    support = object()
    policy: dict[str, object] = {"support": support, "row_version": 7}
    error = AuthorizationDenied()

    @contextmanager
    def tenant(actual_org: UUID, capability: Capability) -> Iterator[tuple[object, None]]:
        assert actual_org == org and capability == Capability.ACQUIRE_SOURCE
        connection = object()
        connections.append(connection)
        active.append(connection)
        events.append("service_begin")
        try:
            yield connection, None
            events.append("service_end")
            if failure == "service_end":
                raise error
            events.append("commit")
            if failure == "commit":
                raise error
        finally:
            active.remove(connection)

    def prepare(connection: object, actual_org: UUID, actual_job: UUID) -> dict[str, object]:
        assert active == [connection] and (actual_org, actual_job) == (org, job)
        events.append("prepare")
        if failure == "prepare":
            raise error
        return dict(row)

    def scope(
        connection: object, actual_org: UUID, actual_job: UUID, actual_url: str, *, browser: bool
    ) -> dict[str, object]:
        assert actual_url == url and browser is False
        return prepare(connection, actual_org, actual_job)

    def authorize(
        connection: object,
        actual_org: UUID,
        actual_job: UUID,
        version: int,
        actual_url: str,
        search: bool,
    ) -> dict[str, object]:
        assert active == [connection]
        assert (actual_org, actual_job, version, actual_url, search) == (
            org,
            job,
            1,
            url,
            kind == "discover",
        )
        events.append("authorize")
        if failure == "authorize":
            raise error  # Includes expiry after preparation, before final authorization.
        return dict(policy)

    def registered(actual_support: object, source: str) -> Any:
        assert not active  # Includes successful service_end and commit, before return.
        assert actual_support is support and source == catalog.SOURCE
        events.append("registry")
        return documents

    monkeypatch.setattr(catalog, "documents", registered)
    journey = object.__new__(ProviderJourney)
    journey.progress = SimpleNamespace(
        discovery=SimpleNamespace(_tenant=tenant, _prepare=prepare, _authorize=authorize)
    )  # type: ignore[assignment]
    journey.xml = SimpleNamespace(_scope=scope)  # type: ignore[assignment]
    if failure:
        with pytest.raises(AuthorizationDenied) as caught:
            journey._request(work)
        assert caught.value is error
        assert "registry" not in events and not active
    else:
        first = journey._request(work)
        assert first[1]["policy_revision"] == 7
        policy["row_version"] = 8
        second = journey._request(work)
        assert second[1]["policy_revision"] == 8
        assert len(connections) == 2 and connections[0] is not connections[1]
        assert (
            events
            == ["service_begin", "prepare", "authorize", "service_end", "commit", "registry"] * 2
        )
        failure = "authorize"  # A later callback must not reuse the earlier policy.
        with pytest.raises(AuthorizationDenied):
            journey._request(work)
        assert len(connections) == 3 and not active


def test_xml_scope_uses_identical_inherited_article_guards() -> None:
    assert XmlExtraction.prepare is Extraction.prepare
    assert XmlExtraction._scope is Extraction._scope


def test_public_discovery_prepare_still_owns_transaction() -> None:
    events: list[str] = []
    connection = object()
    result: dict[str, object] = {"revision": 3}
    discovery = object.__new__(Discovery)

    @contextmanager
    def tenant(org: UUID, capability: Capability) -> Iterator[tuple[object, None]]:
        assert capability == Capability.ACQUIRE_SOURCE
        events.append("begin")
        yield connection, None
        events.append("commit")

    def prepare(c: object, org: UUID, job: UUID) -> dict[str, object]:
        assert c is connection
        events.append("prepare")
        return result

    discovery._tenant = tenant  # type: ignore[method-assign, assignment]
    discovery._prepare = prepare  # type: ignore[method-assign]
    assert discovery.prepare(UUID(int=1), UUID(int=2)) is result
    assert events == ["begin", "prepare", "commit"]


def test_discovery_preparation_preserves_every_original_guard() -> None:
    import textwrap

    method = ast.parse(textwrap.dedent(inspect.getsource(Discovery._prepare))).body[0]
    assert isinstance(method, ast.FunctionDef)
    body = ast.Module(body=method.body[1:], type_ignores=[])
    # Frozen pre-refactor body, excluding only the new private helper docstring.
    assert (
        hashlib.sha256(ast.dump(body, include_attributes=False).encode()).hexdigest()
        == "1c8e26289ffb533e6b3f7af8f4743003b31df3ae1a0c4add310f98acda0a1d13"
    )
