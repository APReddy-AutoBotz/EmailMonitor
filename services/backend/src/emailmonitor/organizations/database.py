"""Parameterized, transaction-local context with bounded identity bootstrap."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from emailmonitor.organizations.roles import ROLE_CAPABILITIES, Capability, Role


class AuthorizationDenied(Exception):
    pass


class RevisionConflict(Exception):
    pass


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class TenantContext:
    organization_id: UUID
    identity_id: UUID
    role: Role
    organization_status: str


class _ConnectionPool:
    def __init__(self, url: str, authentication: bool) -> None:
        self.engine: Engine = create_engine(
            url, pool_size=1, max_overflow=0, pool_pre_ping=True, hide_parameters=True
        )
        forbidden = "emailmonitor_runtime" if authentication else "emailmonitor_authenticator"
        try:
            with self.engine.connect() as connection:
                unsafe: bool = connection.execute(
                    text("""SELECT rolsuper OR rolbypassrls OR current_user<>session_user OR
                    pg_has_role(current_user,'emailmonitor_owner','MEMBER') OR
                    pg_has_role(current_user,'emailmonitor_owner','SET') OR
                    pg_has_role(current_user,:forbidden,'MEMBER') OR
                    pg_has_role(current_user,:forbidden,'SET') FROM pg_roles
                    WHERE rolname=current_user"""),
                    {"forbidden": forbidden},
                ).scalar_one()
                bootstrap: bool = connection.execute(
                    text("""SELECT has_function_privilege(current_user,
                    'emailmonitor.establish_session(text,text,text,text)','EXECUTE')""")
                ).scalar_one()
                if unsafe or bootstrap != authentication:
                    raise ValueError(
                        "Database login must be non-owner with isolated "
                        "authentication/runtime privileges"
                    )
        except Exception:
            self.engine.dispose()
            raise

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            yield connection


class AuthenticationDatabase(_ConnectionPool):
    """Trusted verifier pool: bootstrap functions only, no tenant role membership."""

    def __init__(self, url: str) -> None:
        super().__init__(url, authentication=True)


class Database(_ConnectionPool):
    """Tenant pool: cannot mint sessions or assume authentication/owner roles."""

    def __init__(self, url: str) -> None:
        super().__init__(url, authentication=False)

    @contextmanager
    def tenant(
        self,
        token: str,
        organization_id: UUID,
        capability: Capability,
        allow_inactive: bool = False,
    ) -> Iterator[tuple[Connection, TenantContext]]:
        with self.transaction() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM emailmonitor.resolve_membership(:token,:org)"),
                    {"token": digest(token), "org": organization_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AuthorizationDenied()
            role = Role(row["role"])
            if capability not in ROLE_CAPABILITIES[role]:
                raise AuthorizationDenied()
            status = str(row["organization_status"])
            if status != "active" and not (
                allow_inactive and role == Role.OWNER and status != "deleted"
            ):
                raise AuthorizationDenied()
            context = TenantContext(organization_id, row["identity_id"], role, status)
            connection.execute(
                text(
                    "SELECT set_config('emailmonitor.session_hash',:token,true), "
                    "set_config('emailmonitor.organization_id',:org,true), "
                    "set_config('emailmonitor.lifecycle_recovery',:recovery,true)"
                ),
                {
                    "token": digest(token),
                    "org": str(organization_id),
                    "recovery": str(allow_inactive).lower(),
                },
            )
            yield connection, context
