"""Pure trusted advice grammar. Actual shared admission requires real PostgreSQL CI."""

import ast
import json
from pathlib import Path
from uuid import uuid4

import pytest
from emailmonitor.administration.admission import FixtureAdvice
from pydantic import ValidationError


@pytest.mark.parametrize(
    "value",
    [
        {"admitted": True, "inherited": True, "reference": None},
        {"admitted": True, "inherited": False, "reference": str(uuid4())},
        {"admitted": False, "inherited": False, "reference": str(uuid4())},
    ],
)
def test_owned_advice_shapes(value: dict[str, object]) -> None:
    assert FixtureAdvice.model_validate_json(json.dumps(value)).inherited is value["inherited"]


@pytest.mark.parametrize(
    "value",
    [
        {"admitted": True, "inherited": False, "reference": None},
        {"admitted": False, "inherited": True, "reference": None},
        {"admitted": True, "inherited": True, "reference": str(uuid4())},
        {"admitted": 1, "inherited": False, "reference": str(uuid4())},
        {"admitted": True, "inherited": False, "reference": "unknown"},
        {"admitted": True, "inherited": True, "reference": None, "capacity_bypass": True},
    ],
)
def test_untrusted_advice_states_refuse(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FixtureAdvice.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "value",
    [
        {"admitted": True, "wait_seconds": 0.0},
        {"admitted": False, "wait_seconds": 0.05},
        {"admitted": False, "wait_seconds": 1.0},
    ],
)
def test_source_advice_is_bounded(value: dict[str, object]) -> None:
    from emailmonitor.administration.source import SourceAdvice

    SourceAdvice.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "value",
    [
        {"admitted": True, "wait_seconds": 0.05},
        {"admitted": False, "wait_seconds": 0.0},
        {"admitted": False, "wait_seconds": 1.1},
        {"admitted": 1, "wait_seconds": 0.0},
        {"admitted": True, "wait_seconds": False},
        {"admitted": True, "wait_seconds": 0.0, "unlimited": True},
    ],
)
def test_source_advice_cannot_expand_delay_or_permission(value: dict[str, object]) -> None:
    from emailmonitor.administration.source import SourceAdvice

    with pytest.raises(ValidationError):
        SourceAdvice.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("field", ["identifier", "nonce", "organization"])
def test_source_lease_requires_exact_owned_uuid_types(field: str) -> None:
    from emailmonitor.administration.source import SourceLease
    from emailmonitor.fetching.safety import FetchDenied

    values = {"identifier": uuid4(), "nonce": uuid4(), "organization": uuid4()}
    values[field] = "untrusted"  # type: ignore[assignment]
    with pytest.raises(FetchDenied):
        SourceLease(**values)


def test_provider_backoff_can_only_postpone_and_unsafe_headers_are_not_forwarded() -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager
    from typing import Any

    from emailmonitor.administration.source import SourceAdmission, SourceLease

    class Recording(SourceAdmission):
        def __init__(self) -> None:
            self.replies: list[dict[str, object]] = []

        @contextmanager
        def _tenant(self, organization: Any, capability: Any) -> Iterator[Any]:
            recorder = self

            class Connection:
                def execute(self, statement: object, parameters: dict[str, object]) -> None:
                    recorder.replies.append(parameters)

            yield Connection()

    source = Recording()
    ticket = SourceLease(uuid4(), uuid4(), uuid4())
    for header, expected in (
        ("0", 5),
        ("12", 12),
        ("99999", -1),
        ("Wed, synthetic", -1),
        ("1\nsecret", -1),
    ):
        source.finish(ticket, 429, header)
        assert source.replies[-1]["delay"] == expected
        assert source.replies[-1]["outcome"] == "provider_backoff"
        assert "retry_after" not in source.replies[-1]
    source.finish(ticket, 200, "99999")
    assert source.replies[-1]["delay"] == 0 and source.replies[-1]["outcome"] == "response"


def test_refused_success_performs_only_owned_failure_cleanup_and_still_denies() -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager
    from typing import Any

    from emailmonitor.administration.source import SourceAdmission, SourceLease
    from emailmonitor.fetching.safety import FetchDenied
    from emailmonitor.organizations.database import AuthorizationDenied

    class Recording(SourceAdmission):
        def __init__(self) -> None:
            self.outcomes: list[dict[str, object]] = []

        @contextmanager
        def _tenant(self, organization: Any, capability: Any) -> Iterator[Any]:
            recorder = self

            class Connection:
                def execute(self, statement: object, parameters: dict[str, object]) -> None:
                    recorder.outcomes.append(parameters)
                    if parameters["outcome"] != "network_failure":
                        raise AuthorizationDenied()

            yield Connection()

    source = Recording()
    owned = SourceLease(uuid4(), uuid4(), uuid4())
    with pytest.raises(FetchDenied):
        source.finish(owned, 200)
    assert [row["outcome"] for row in source.outcomes] == ["response", "network_failure"]
    assert all(
        row["id"] == owned.identifier and row["nonce"] == owned.nonce for row in source.outcomes
    )


def test_source_claim_sql_literals_have_no_leading_quote_artifacts() -> None:
    """Keep skipped service assertions syntactically faithful to their SQL contract."""
    module = ast.parse(Path(__file__).with_name("test_admission_tenant.py").read_text())
    statements = [
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "SELECT emailmonitor.source_resource_claim(" in node.value
    ]
    assert statements
    for statement in statements:
        assert statement.lstrip().startswith("SELECT emailmonitor.source_resource_claim(")
        assert not statement.lstrip().startswith('"')


def test_admission_pool_record_name_cannot_shadow_conflict_column() -> None:
    root = Path(__file__).resolve().parents[3]
    sql = (root / "services/backend/migrations/versions/0010_administration.sql").read_text()
    function = sql.split("CREATE FUNCTION emailmonitor.admission_try(", 1)[1].split("END $$;", 1)[0]
    assert "pool_state emailmonitor.admission_pools" in function
    assert " pool emailmonitor.admission_pools" not in function
    assert "ON CONFLICT(organization_id,pool,reference_id,generation)" in function
    assert "active>=pool_state.maximum" in function


def test_owned_mutex_observation_refreshes_current_query_snapshot_before_poll() -> None:
    module = ast.parse(Path(__file__).with_name("test_admission_tenant.py").read_text())
    outer = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_real_contended_source_grant_and_backoff_use_post_lock_time"
    )
    observer = next(
        node
        for node in outer.body
        if isinstance(node, ast.FunctionDef) and node.name == "contended"
    )
    loop = next(node for node in observer.body if isinstance(node, ast.While))
    assert isinstance(loop.body[0], ast.Expr)
    assert "SELECT pg_stat_clear_snapshot()" in ast.unparse(loop.body[0])
    assert "pg_stat_activity" in ast.unparse(loop.body[1])
