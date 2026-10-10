"""Offline-tested OIDC/session and tenant API assembly, disabled in production."""

import secrets
from dataclasses import dataclass
from hmac import compare_digest
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from emailmonitor.config import Settings
from emailmonitor.identity.oidc import AuthenticationDenied, OIDCProvider
from emailmonitor.organizations.database import (
    AuthenticationDatabase,
    AuthorizationDenied,
    Database,
    TenantContext,
    digest,
)
from emailmonitor.organizations.roles import LIFECYCLE_TRANSITIONS, Capability, Role
from emailmonitor.sources.api import source_router

COOKIE = "__Host-emailmonitor_session"
FLOW_COOKIE = "__Host-emailmonitor_login"


class MembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    status: Literal["active", "revoked"]
    expected_revision: int = Field(ge=1)


class MembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity_id: UUID
    role: Role


class OwnerTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_identity_id: UUID
    expected_revision: int = Field(ge=1)


class LifecycleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "suspended", "offboarding", "deleted"]
    expected_revision: int = Field(ge=1)


@dataclass(frozen=True)
class Foundation:
    database: Database
    provider: OIDCProvider
    authentication: AuthenticationDatabase

    def router(self, settings: Settings) -> APIRouter:
        if (
            settings.environment != "test"
            or not settings.identity_stub
            or not self.provider.test_only
        ):
            raise ValueError(
                "EM-002 provider assembly is test-only; production activation is unavailable"
            )
        router = APIRouter(prefix="/api/v1")

        def token(request: Request) -> str:
            value = request.cookies.get(COOKIE)
            if not value or len(value) > 256:
                raise HTTPException(401, "Authentication required")
            return value

        def csrf(request: Request) -> str:
            value = token(request)
            if request.headers.get("origin") != self.provider.origin:
                raise HTTPException(403, "Request not permitted")
            supplied = request.headers.get("x-csrf-token", "")
            with self.database.transaction() as connection:
                row = (
                    connection.execute(
                        text("SELECT * FROM emailmonitor.resolve_session(:token)"),
                        {"token": digest(value)},
                    )
                    .mappings()
                    .first()
                )
            if row is None or not compare_digest(row["csrf_hash"], digest(supplied)):
                raise HTTPException(403, "Request not permitted")
            return value

        def audit(
            connection: Connection, context: TenantContext, action: str, resource: UUID
        ) -> None:
            connection.execute(
                text("""
INSERT INTO emailmonitor.audit_events
(organization_id,id,actor_id,action,resource_id)
VALUES(:org,:id,:actor,:action,:resource)
"""),
                {
                    "org": context.organization_id,
                    "id": uuid4(),
                    "actor": context.identity_id,
                    "action": action,
                    "resource": resource,
                },
            )

        @router.get("/auth/start")
        def start() -> RedirectResponse:
            state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
            with self.authentication.transaction() as connection:
                connection.execute(
                    text("SELECT emailmonitor.put_login_flow(:state,:nonce,:verifier)"),
                    {"state": digest(state), "nonce": nonce, "verifier": verifier},
                )
            response = RedirectResponse(
                self.provider.authorization_url(state, nonce, verifier), 303
            )
            response.set_cookie(
                FLOW_COOKIE,
                state,
                secure=True,
                httponly=True,
                samesite="lax",
                max_age=300,
                path="/",
            )
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.get("/auth/callback")
        def callback(request: Request, state: str, code: str) -> Response:
            supplied = request.cookies.get(FLOW_COOKIE, "")
            if len(state) > 256 or len(code) > 4096 or not compare_digest(state, supplied):
                raise HTTPException(401, "Authentication failed")
            with self.authentication.transaction() as connection:
                flow = (
                    connection.execute(
                        text("SELECT * FROM emailmonitor.consume_login_flow(:state)"),
                        {"state": digest(state)},
                    )
                    .mappings()
                    .first()
                )
            if flow is None:
                raise HTTPException(401, "Authentication failed")
            try:
                issuer, subject = self.provider.verify_code(code, flow["verifier"], flow["nonce"])
                session_token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with self.authentication.transaction() as connection:
                    connection.execute(
                        text(
                            "SELECT emailmonitor.establish_session(:issuer,:subject,:token,:csrf)"
                        ),
                        {
                            "issuer": issuer,
                            "subject": subject,
                            "token": digest(session_token),
                            "csrf": digest(csrf_token),
                        },
                    )
            except (AuthenticationDenied, SQLAlchemyError) as error:
                raise HTTPException(401, "Authentication failed") from error
            response = JSONResponse({"authenticated": True, "csrf_token": csrf_token})
            response.set_cookie(
                COOKIE,
                session_token,
                secure=True,
                httponly=True,
                samesite="lax",
                max_age=3600,
                path="/",
            )
            response.delete_cookie(
                FLOW_COOKIE, secure=True, httponly=True, samesite="lax", path="/"
            )
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.post("/auth/logout")
        def logout(request: Request) -> Response:
            session_token = csrf(request)
            with self.database.transaction() as connection:
                connection.execute(
                    text("SELECT emailmonitor.revoke_session(:token)"),
                    {"token": digest(session_token)},
                )
            response = Response(status_code=204)
            response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax", path="/")
            return response

        @router.get("/me")
        def me(request: Request) -> dict[str, object]:
            session_token = token(request)
            with self.database.transaction() as connection:
                identity = connection.execute(
                    text("SELECT identity_id FROM emailmonitor.resolve_session(:token)"),
                    {"token": digest(session_token)},
                ).scalar()
                if identity is None:
                    raise HTTPException(401, "Authentication required")
                memberships = (
                    connection.execute(
                        text("SELECT * FROM emailmonitor.list_memberships(:token)"),
                        {"token": digest(session_token)},
                    )
                    .mappings()
                    .all()
                )
                return {
                    "identity_id": str(identity),
                    "memberships": [dict(row) for row in memberships],
                }

        @router.get("/organizations/{organization_id}")
        def organization(request: Request, organization_id: UUID) -> dict[str, object]:
            with self.database.tenant(
                token(request), organization_id, Capability.READ_ORGANIZATION
            ) as (connection, _):
                row = (
                    connection.execute(
                        text(
                            """
SELECT id,display_name,status,region,timezone,row_version FROM
emailmonitor.organizations WHERE id=:org
"""
                        ),
                        {"org": organization_id},
                    )
                    .mappings()
                    .one()
                )
                return dict(row)

        @router.get("/organizations/{organization_id}/members")
        def members(request: Request, organization_id: UUID) -> list[dict[str, object]]:
            with self.database.tenant(
                token(request), organization_id, Capability.MANAGE_MEMBERS
            ) as (connection, _):
                return [
                    dict(row)
                    for row in connection.execute(
                        text(
                            """
SELECT identity_id,role,status,row_version FROM emailmonitor.memberships WHERE
organization_id=:org ORDER BY identity_id
"""
                        ),
                        {"org": organization_id},
                    ).mappings()
                ]

        @router.post("/organizations/{organization_id}/members", status_code=201)
        def create_member(
            request: Request, organization_id: UUID, body: MembershipCreate
        ) -> dict[str, object]:
            with self.database.tenant(
                csrf(request), organization_id, Capability.MANAGE_MEMBERS
            ) as (connection, context):
                if body.role == Role.OWNER and context.role != Role.OWNER:
                    raise AuthorizationDenied()
                allowed: bool = connection.execute(
                    text("SELECT emailmonitor.member_identity_allowed(:identity,:issuer)"),
                    {"identity": body.identity_id, "issuer": self.provider.issuer},
                ).scalar_one()
                if not allowed:
                    raise AuthorizationDenied()
                audit(connection, context, "membership.created", body.identity_id)
                connection.execute(
                    text(
                        "INSERT INTO emailmonitor.memberships "
                        "VALUES(:org,:identity,:role,'active',1)"
                    ),
                    {"org": organization_id, "identity": body.identity_id, "role": body.role.value},
                )
                return {"identity_id": body.identity_id, "role": body.role.value, "row_version": 1}

        @router.patch("/organizations/{organization_id}/members/{identity_id}")
        def update_member(
            request: Request, organization_id: UUID, identity_id: UUID, body: MembershipUpdate
        ) -> dict[str, object]:
            with self.database.tenant(
                csrf(request), organization_id, Capability.MANAGE_MEMBERS
            ) as (connection, context):
                connection.execute(
                    text("SELECT id FROM emailmonitor.organizations WHERE id=:org FOR UPDATE"),
                    {"org": organization_id},
                )
                member = (
                    connection.execute(
                        text(
                            """
SELECT role,row_version FROM emailmonitor.memberships WHERE
organization_id=:org AND identity_id=:identity FOR UPDATE
"""
                        ),
                        {"org": organization_id, "identity": identity_id},
                    )
                    .mappings()
                    .first()
                )
                if member is None:
                    raise AuthorizationDenied()
                if (
                    body.role == Role.OWNER or member["role"] == "owner"
                ) and context.role != Role.OWNER:
                    raise AuthorizationDenied()
                if member["row_version"] != body.expected_revision:
                    raise HTTPException(409, "Revision conflict")
                audit(connection, context, "membership.updated", identity_id)
                connection.execute(
                    text(
                        """
UPDATE emailmonitor.memberships SET role=:role,status=:status WHERE
organization_id=:org AND identity_id=:identity
"""
                    ),
                    {
                        "org": organization_id,
                        "identity": identity_id,
                        "role": body.role.value,
                        "status": body.status,
                    },
                )
                return {"row_version": body.expected_revision + 1}

        @router.post("/organizations/{organization_id}/owner-transfer")
        def transfer_owner(
            request: Request, organization_id: UUID, body: OwnerTransfer
        ) -> dict[str, object]:
            with self.database.tenant(
                csrf(request), organization_id, Capability.TRANSFER_OWNER
            ) as (connection, context):
                if body.target_identity_id == context.identity_id:
                    raise HTTPException(409, "Transfer requires another active member")
                connection.execute(
                    text("SELECT id FROM emailmonitor.organizations WHERE id=:org FOR UPDATE"),
                    {"org": organization_id},
                )
                target = (
                    connection.execute(
                        text(
                            """
SELECT row_version,status FROM emailmonitor.memberships WHERE
organization_id=:org AND identity_id=:target FOR UPDATE
"""
                        ),
                        {"org": organization_id, "target": body.target_identity_id},
                    )
                    .mappings()
                    .first()
                )
                if target is None or target["status"] != "active":
                    raise AuthorizationDenied()
                if target["row_version"] != body.expected_revision:
                    raise HTTPException(409, "Revision conflict")
                audit(connection, context, "owner.transferred", body.target_identity_id)
                connection.execute(
                    text(
                        """
UPDATE emailmonitor.memberships SET role='owner' WHERE organization_id=:org
AND identity_id=:target
"""
                    ),
                    {"org": organization_id, "target": body.target_identity_id},
                )
                connection.execute(
                    text(
                        """
UPDATE emailmonitor.memberships SET role='admin' WHERE organization_id=:org
AND identity_id=:actor
"""
                    ),
                    {"org": organization_id, "actor": context.identity_id},
                )
                return {"transferred": True}

        @router.post("/organizations/{organization_id}/lifecycle")
        def lifecycle(
            request: Request, organization_id: UUID, body: LifecycleUpdate
        ) -> dict[str, object]:
            with self.database.tenant(
                csrf(request), organization_id, Capability.MANAGE_LIFECYCLE, allow_inactive=True
            ) as (connection, context):
                row = (
                    connection.execute(
                        text(
                            "SELECT status,row_version FROM emailmonitor.organizations "
                            "WHERE id=:org FOR UPDATE"
                        ),
                        {"org": organization_id},
                    )
                    .mappings()
                    .one()
                )
                if (
                    row["row_version"] != body.expected_revision
                    or body.status not in LIFECYCLE_TRANSITIONS[row["status"]]
                ):
                    raise HTTPException(409, "Revision or lifecycle conflict")
                audit(connection, context, "organization.lifecycle", organization_id)
                connection.execute(
                    text("UPDATE emailmonitor.organizations SET status=:status WHERE id=:org"),
                    {"org": organization_id, "status": body.status},
                )
                return {"status": body.status, "row_version": body.expected_revision + 1}

        router.include_router(source_router(self.database, token, csrf, audit))
        return router
