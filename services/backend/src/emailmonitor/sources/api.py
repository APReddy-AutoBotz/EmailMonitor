"""Tenant-authorized offline governance. Approval never acquires source content."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid5

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import Connection, text

from emailmonitor.organizations.database import Database, TenantContext
from emailmonitor.organizations.roles import Capability
from emailmonitor.sources.policy import (
    Evaluation,
    PolicyProposal,
    Revision,
    Transition,
    validate_approval,
)


def source_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    audit: Callable[[Connection, TenantContext, str, UUID], None],
) -> APIRouter:
    router = APIRouter()

    def current(connection: Connection, organization: UUID, source: str) -> dict[str, object]:
        row = (
            connection.execute(
                text("""
SELECT p.*,s.enabled,s.support FROM emailmonitor.source_policies p
JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
JOIN emailmonitor.source_catalog s USING(source_id)
WHERE p.organization_id=:org AND p.source_id=:source AND p.version=h.current_version
"""),
                {"org": organization, "source": source},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(404, "Policy unavailable")
        return dict(row)

    def lock(connection: Connection, organization: UUID, source: str) -> int:
        exists = connection.execute(
            text("SELECT source_id FROM emailmonitor.source_catalog WHERE source_id=:source"),
            {"source": source},
        ).scalar()
        if exists is None:
            raise HTTPException(404, "Source unavailable")
        connection.execute(
            text("""
INSERT INTO emailmonitor.source_policy_heads(organization_id,source_id)
VALUES(:org,:source) ON CONFLICT DO NOTHING
"""),
            {"org": organization, "source": source},
        )
        return int(
            connection.execute(
                text("""
SELECT current_version FROM emailmonitor.source_policy_heads
WHERE organization_id=:org AND source_id=:source FOR UPDATE
"""),
                {"org": organization, "source": source},
            ).scalar_one()
        )

    def public(row: dict[str, object]) -> dict[str, object]:
        proposal = PolicyProposal.model_validate(row["policy"])
        state = str(row["state"])
        if state == "approved" and proposal.valid_until <= datetime.now(UTC):
            state = "expired"
        result = proposal.model_dump(mode="json")
        result.update(
            {
                "schema_version": "1.0",
                "organization_id": str(row["organization_id"]),
                "source_id": row["source_id"],
                "version": row["version"],
                "state": state,
                "reviewed_by": str(row["reviewed_by"]) if row["reviewed_by"] else None,
                "approved_at": row["approved_at"],
                "row_version": row["row_version"],
                "export_contacts_allowed": state == "approved" and proposal.export_contacts_allowed,
            }
        )
        return result

    @router.get("/organizations/{organization_id}/sources")
    def catalog(request: Request, organization_id: UUID) -> list[dict[str, object]]:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            return [
                dict(row)
                for row in c.execute(
                    text("SELECT * FROM emailmonitor.source_catalog ORDER BY source_id")
                ).mappings()
            ]

    @router.get("/organizations/{organization_id}/sources/{source_id}/policies")
    def history(request: Request, organization_id: UUID, source_id: str) -> list[dict[str, object]]:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            return [
                public(dict(row))
                for row in c.execute(
                    text("""
SELECT * FROM emailmonitor.source_policies WHERE organization_id=:org AND source_id=:source
ORDER BY version DESC LIMIT 100
"""),
                    {"org": organization_id, "source": source_id},
                ).mappings()
            ]

    @router.post("/organizations/{organization_id}/sources/{source_id}/policies", status_code=201)
    def propose(
        request: Request, organization_id: UUID, source_id: str, body: Revision
    ) -> dict[str, object]:
        with database.tenant(csrf(request), organization_id, Capability.MANAGE_SOURCE_POLICY) as (
            c,
            ctx,
        ):
            version = lock(c, organization_id, source_id)
            if version != body.expected_version:
                raise HTTPException(409, "Policy version conflict")
            if body.policy.valid_until <= datetime.now(UTC):
                raise HTTPException(422, "Policy expiry must be in the future")
            c.execute(
                text("""
INSERT INTO emailmonitor.source_policies
(organization_id,source_id,version,state,policy,created_by,valid_until)
VALUES(:org,:source,:version,'pending_review',CAST(:policy AS jsonb),:actor,:expiry)
"""),
                {
                    "org": organization_id,
                    "source": source_id,
                    "version": version + 1,
                    "policy": json.dumps(body.policy.model_dump(mode="json")),
                    "actor": ctx.identity_id,
                    "expiry": body.policy.valid_until,
                },
            )
            c.execute(
                text("""
UPDATE emailmonitor.source_policy_heads SET current_version=:version
WHERE organization_id=:org AND source_id=:source
"""),
                {"org": organization_id, "source": source_id, "version": version + 1},
            )
            audit(c, ctx, "source.policy.proposed", uuid5(organization_id, source_id))
            return public(current(c, organization_id, source_id))

    @router.post("/organizations/{organization_id}/sources/{source_id}/policy-state")
    def transition(
        request: Request, organization_id: UUID, source_id: str, body: Transition
    ) -> dict[str, object]:
        with database.tenant(csrf(request), organization_id, Capability.MANAGE_SOURCE_POLICY) as (
            c,
            ctx,
        ):
            if lock(c, organization_id, source_id) != body.expected_version:
                raise HTTPException(409, "Policy version conflict")
            row = current(c, organization_id, source_id)
            if row["row_version"] != body.expected_revision:
                raise HTTPException(409, "Policy revision conflict")
            if body.state == "approved":
                try:
                    validate_approval(
                        PolicyProposal.model_validate(row["policy"]), datetime.now(UTC)
                    )
                except ValueError as error:
                    raise HTTPException(
                        422, "Approval requires permission and valid expiry"
                    ) from error
            c.execute(
                text("""
UPDATE emailmonitor.source_policies SET state=:state,
reviewed_by=CASE WHEN :state='approved' THEN :actor ELSE reviewed_by END,
approved_at=CASE WHEN :state='approved' THEN now() ELSE approved_at END
WHERE organization_id=:org AND source_id=:source AND version=:version
"""),
                {
                    "org": organization_id,
                    "source": source_id,
                    "version": body.expected_version,
                    "state": body.state,
                    "actor": ctx.identity_id,
                },
            )
            audit(c, ctx, "source.policy." + body.state, uuid5(organization_id, source_id))
            return public(current(c, organization_id, source_id))

    @router.post("/organizations/{organization_id}/sources/{source_id}/evaluate")
    def evaluate(
        request: Request, organization_id: UUID, source_id: str, body: Evaluation
    ) -> dict[str, object]:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            row = current(c, organization_id, source_id)
            policy = PolicyProposal.model_validate(row["policy"])
            support = row["support"]
            routes = support.get("routes_by_operation", {}) if isinstance(support, dict) else {}
            route_allowed = isinstance(routes, dict) and body.path in routes.get(body.operation, [])
            approved = (
                route_allowed
                and row["version"] == body.expected_version
                and row["enabled"] is True
                and row["state"] == "approved"
                and policy.valid_until > datetime.now(UTC)
                and body.execution_mode == "fixture"
                and body.host in policy.allowed_hosts
                and body.operation in policy.allowed_operations
                and (body.operation != "export_contacts" or policy.export_contacts_allowed)
            )
            return {
                "policy_authorized": approved,
                "version": row["version"],
                "execution_available": False,
                "execution_mode": "fixture",
                "reason": "offline_policy_only" if approved else "policy_denied",
            }

    return router
