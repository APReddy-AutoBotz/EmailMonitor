"""Real cached-function freshness on guarded disposable SQL, never mock proof."""

import time
from uuid import UUID, uuid4

import pytest
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.models import ExportInput
from emailmonitor.results.service import Results
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_progress_tenant import drain
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def current(connection: Connection, org: UUID | None, grant: UUID | None) -> bool:
    result: bool = connection.execute(
        text("SELECT emailmonitor.service_delegation_current(:org,:grant)"),
        {"org": org, "grant": grant},
    ).scalar_one()
    return result


def warm(connection: Connection, org: UUID, grant: UUID) -> tuple[int, int]:
    connection.execute(text("SET LOCAL lock_timeout='2000ms'"))
    connection.execute(text("SET LOCAL statement_timeout='5000ms'"))
    assert connection.execute(text("SHOW transaction_isolation")).scalar_one() == "read committed"
    assert (
        connection.execute(
            text(
                "SELECT l.lanname FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang "
                "WHERE p.oid='emailmonitor.service_delegation_current(uuid,uuid)'::regprocedure"
            )
        ).scalar_one()
        == "plpgsql"
    )
    row = connection.execute(text("SELECT pg_backend_pid(),txid_current()")).one()
    identity = (int(str(row[0])), int(str(row[1])))
    for _ in range(6):
        assert current(connection, org, grant) is True
    return identity


@pytest.mark.parametrize(
    "mutation",
    [
        "delegation",
        "policy",
        "principal",
        "identity",
        "session",
        "membership",
        "catalog",
    ],
)
def test_warm_same_session_function_observes_committed_authority_change(
    service_case: ServiceCase,
    scenario: Scenario,
    mutation: str,
) -> None:
    case = service_case
    org = case.scope.organization
    statements = {
        "delegation": (
            "UPDATE emailmonitor.service_delegations SET revoked_at=clock_timestamp() "
            "WHERE id=:grant"
        ),
        "policy": (
            "UPDATE emailmonitor.source_policies SET state='revoked' "
            "WHERE organization_id=:org AND source_id='synthetic-publisher'"
        ),
        "principal": "UPDATE emailmonitor.service_principals SET active=false WHERE id=:principal",
        "identity": "UPDATE emailmonitor.identities SET active=false WHERE id=:actor",
        "session": (
            "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() WHERE token_hash="
            "(SELECT origin_session_hash FROM emailmonitor.service_delegations WHERE id=:grant)"
        ),
        "membership": (
            "UPDATE emailmonitor.memberships SET status='revoked' "
            "WHERE organization_id=:org AND identity_id=:actor"
        ),
        "catalog": (
            "UPDATE emailmonitor.source_catalog SET enabled=false "
            "WHERE source_id='synthetic-publisher'"
        ),
    }
    try:
        with case.admin.connect() as reader:
            identity = warm(reader, org, case.grant)
            for other_org, other_grant in (
                (scenario.organizations[1], case.grant),
                (org, uuid4()),
                (None, case.grant),
                (org, None),
                (None, None),
            ):
                assert current(reader, other_org, other_grant) is False
            with case.admin.begin() as writer:
                writer.execute(text("SET LOCAL lock_timeout='2000ms'"))
                writer.execute(text("SET LOCAL statement_timeout='5000ms'"))
                result = writer.execute(
                    text(statements[mutation]),
                    {
                        "org": org,
                        "grant": case.grant,
                        "principal": case.principal,
                        "actor": scenario.identities["owner"],
                    },
                )
                assert result.rowcount == 1
            # Reader has neither committed nor checked its connection back in.
            assert (
                tuple(reader.execute(text("SELECT pg_backend_pid(),txid_current()")).one())
                == identity
            )
            assert current(reader, org, case.grant) is False
    finally:
        if mutation == "catalog":
            with case.admin.begin() as writer:
                writer.execute(text("SET LOCAL lock_timeout='2000ms'"))
                writer.execute(text("SET LOCAL statement_timeout='5000ms'"))
                writer.execute(
                    text(
                        "UPDATE emailmonitor.source_catalog SET enabled=true "
                        "WHERE source_id='synthetic-publisher'"
                    )
                )


def test_warm_export_function_natural_deadline_and_private_execute(
    service_case: ServiceCase,
) -> None:
    case = service_case
    org, job = case.scope.organization, case.scope.resource
    # Private helper remains inaccessible to the service login after replacement.
    with pytest.raises(DBAPIError) as denied:
        with case.database.engine.begin() as worker:
            worker.execute(
                text("SELECT emailmonitor.service_delegation_current(:org,:grant)"),
                {"org": org, "grant": case.grant},
            )
    assert denied.value.orig is not None
    detail = denied.value.orig.args[0]
    assert isinstance(detail, dict) and detail.get("C") == "42501"
    drain(case.progress, org, job)
    human = Results(case.progress.database, case.progress.token, SETTINGS)
    exported = human.create(
        org,
        ExportInput.model_validate(
            {
                "job_id": str(job),
                "format": "xlsx",
                "purpose": "academic_contact_research",
            }
        ),
        str(uuid4()),
    )
    with case.progress.database.tenant(case.progress.token, org, Capability.EXPORT_RESULTS) as (
        c,
        _,
    ):
        grant: UUID = c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work(:org,:principal,:resource,'export',10)"
            ),
            {"org": org, "principal": case.principal, "resource": exported.id},
        ).scalar_one()
    with case.admin.connect() as reader:
        identity = warm(reader, org, grant)
        # Session expiry itself deliberately does not invalidate delegated work.
        with case.admin.begin() as writer:
            writer.execute(text("SET LOCAL lock_timeout='2000ms'"))
            writer.execute(text("SET LOCAL statement_timeout='5000ms'"))
            writer.execute(
                text(
                    "UPDATE emailmonitor.sessions "
                    "SET expires_at=clock_timestamp()-interval '1 second' "
                    "WHERE token_hash=(SELECT origin_session_hash "
                    "FROM emailmonitor.service_delegations "
                    "WHERE id=:grant)"
                ),
                {"grant": grant},
            )
        assert current(reader, org, grant) is True
        # Keep the immutable normally minted deadline. Each sleep is below the
        # existing five-second statement cap; neither stalls nor early expiry
        # cause reissuance or renewal of the grant.
        wait_until = time.monotonic() + 11
        for attempt in range(7):
            assert time.monotonic() < wait_until, "Bounded expiry wait exhausted"
            remaining = float(
                reader.execute(
                    text(
                        "SELECT extract(epoch FROM deadline-clock_timestamp()) "
                        "FROM emailmonitor.service_delegations WHERE id=:grant"
                    ),
                    {"grant": grant},
                ).scalar_one()
            )
            if attempt == 0:
                assert 0 < remaining <= 10
            if remaining <= 0:
                break
            assert time.monotonic() < wait_until, "Bounded expiry wait exhausted"
            reader.execute(
                text("SELECT pg_sleep(:seconds)"),
                {"seconds": min(2, remaining + 0.02)},
            )
        else:
            raise AssertionError("Bounded server-clock expiry did not occur")
        assert time.monotonic() < wait_until
        # clock_timestamp, not transaction time, must determine the next result.
        assert (
            tuple(reader.execute(text("SELECT pg_backend_pid(),txid_current()")).one()) == identity
        )
        assert current(reader, org, grant) is False
