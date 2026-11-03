"""Dedicated service-login pool; tenant/work settings are never credentials."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.administration.binding import apply as apply_fixture_binding
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import apply as apply_work_binding
from emailmonitor.runtime.authority import ServiceProcess, ServiceWork


@dataclass(frozen=True, slots=True)
class ServiceContext:
    organization_id: UUID
    principal_id: UUID
    delegation_id: UUID
    work: ServiceWork


class ServiceDatabase:
    """No human role, browser session, bootstrap pool or arbitrary tenant reads."""

    def __init__(self, url: str, process: ServiceProcess) -> None:
        self.process = ServiceProcess.model_validate(process.model_dump())
        self.engine: Engine = create_engine(
            url,
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
            pool_timeout=2,
            connect_args={"timeout": 3},
            hide_parameters=True,
        )
        expected = "emailmonitor_" + process.kind
        other = "emailmonitor_publisher" if process.kind == "worker" else "emailmonitor_worker"
        try:
            with self.engine.connect() as connection:
                unsafe: bool = connection.execute(
                    text("""
SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication
 OR NOT rolcanlogin OR current_user<>session_user
 OR NOT pg_has_role(current_user,:expected,'MEMBER')
 OR pg_has_role(current_user,:other,'MEMBER') OR pg_has_role(current_user,:other,'SET')
 OR pg_has_role(current_user,'emailmonitor_owner','MEMBER')
 OR pg_has_role(current_user,'emailmonitor_owner','SET')
 OR pg_has_role(current_user,'emailmonitor_runtime','MEMBER')
 OR pg_has_role(current_user,'emailmonitor_runtime','SET')
 OR pg_has_role(current_user,'emailmonitor_authenticator','MEMBER')
 OR pg_has_role(current_user,'emailmonitor_authenticator','SET')
 OR has_function_privilege(current_user,
 'emailmonitor.establish_session(text,text,text,text)','EXECUTE')
 OR NOT has_function_privilege(current_user,
 'emailmonitor.service_begin(uuid,uuid,text,bigint,text,uuid)','EXECUTE')
 OR EXISTS(SELECT 1 FROM pg_roles reachable
 WHERE pg_has_role(current_user,reachable.oid,'MEMBER') AND
 (reachable.rolsuper OR reachable.rolbypassrls OR reachable.rolcreaterole
 OR reachable.rolcreatedb OR reachable.rolreplication OR has_function_privilege(
 reachable.oid,'emailmonitor.establish_session(text,text,text,text)','EXECUTE')))
 FROM pg_roles WHERE rolname=current_user
"""),
                    {"expected": expected, "other": other},
                ).scalar_one()
                if not connection.execute(
                    text("SELECT emailmonitor.service_schema_ready()")
                ).scalar_one():
                    raise AuthorizationDenied()
                if unsafe:
                    raise AuthorizationDenied()
                self.organization: UUID = connection.execute(
                    text("SELECT emailmonitor.service_identity(:principal,:kind)"),
                    {"principal": process.principal, "kind": process.kind},
                ).scalar_one()
        except Exception:
            self.engine.dispose()
            raise ValueError("Isolated non-owner service database login required") from None

    @contextmanager
    def tenant(
        self,
        token: str | ServiceWork,
        organization_id: UUID,
        capability: Capability,
        allow_inactive: bool = False,
    ) -> Iterator[tuple[Connection, ServiceContext]]:
        if (
            type(token) is not ServiceWork
            or token.organization != organization_id
            or allow_inactive
            or capability
            not in {
                Capability.READ_ORGANIZATION,
                Capability.ACQUIRE_SOURCE
                if token.purpose == "extraction"
                else Capability.EXPORT_RESULTS,
            }
        ):
            raise AuthorizationDenied()
        scope = ServiceWork.model_validate(token.model_dump())
        params = {
            "org": organization_id,
            "resource": scope.resource,
            "purpose": scope.purpose,
            "generation": scope.generation,
            "kind": self.process.kind,
            "principal": self.process.principal,
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT set_config('lock_timeout','2000ms',true), "
                        "set_config('statement_timeout','5000ms',true)"
                    )
                )
                delegation: UUID = connection.execute(
                    text(
                        "SELECT emailmonitor.service_begin("
                        ":org,:resource,:purpose,:generation,:kind,:principal)"
                    ),
                    params,
                ).scalar_one()
                apply_work_binding(connection, organization_id)
                apply_fixture_binding(connection, organization_id)
                yield (
                    connection,
                    ServiceContext(organization_id, self.process.principal, delegation, scope),
                )
                # Independent database helpers also fence consequential work;
                # this check cannot replace their resource/lease/privacy fences.
                connection.execute(
                    text("SELECT emailmonitor.service_end(:org,:resource,:purpose,:kind)"),
                    params,
                )
        except DBAPIError:
            # Service callers receive no SQL, connection details or source content.
            raise AuthorizationDenied() from None
