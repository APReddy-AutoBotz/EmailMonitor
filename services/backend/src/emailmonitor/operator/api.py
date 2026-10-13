"""Bounded UI support; reuses existing tenant RLS without adding permissions."""

from collections.abc import Callable
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, text

from emailmonitor.organizations.database import AuthorizationDenied, Database, TenantContext
from emailmonitor.organizations.roles import Capability


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: str = Field(min_length=1, max_length=100)
    timezone: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)

    @field_validator("display_name")
    @classmethod
    def printable_name(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Printable nonempty display name required")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Known IANA timezone required") from error
        return value


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    organization_id: UUID
    fixture_probe_initialized: bool
    fixture_probe_maximum: int | None
    fixture_probe_reserved: int | None
    fixture_probe_used: int | None
    retained_extraction_effects: int = Field(ge=0)
    cost: None = None
    billing_implemented: Literal[False] = False
    synthetic_only: Literal[True] = True


def operator_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    audit: Callable[[Connection, TenantContext, str, UUID], None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/organizations/{organization_id}/usage", response_model=Usage)
    def usage(request: Request, organization_id: UUID) -> Usage:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            c.execute(text("SELECT set_config('statement_timeout','5000',true)"))
            quota = (
                c.execute(
                    text("""SELECT maximum,reserved,used FROM emailmonitor.fixture_quota
                WHERE organization_id=:org"""),
                    {"org": organization_id},
                )
                .mappings()
                .first()
            )
            effects = int(
                c.execute(
                    text("""SELECT count(*) FROM emailmonitor.execution_effects
                WHERE organization_id=:org"""),
                    {"org": organization_id},
                ).scalar_one()
            )
            return Usage(
                organization_id=organization_id,
                fixture_probe_initialized=quota is not None,
                fixture_probe_maximum=int(quota["maximum"]) if quota else None,
                fixture_probe_reserved=int(quota["reserved"]) if quota else None,
                fixture_probe_used=int(quota["used"]) if quota else None,
                retained_extraction_effects=effects,
            )

    @router.get("/organizations/{organization_id}/audit")
    def history(
        request: Request,
        organization_id: UUID,
        cursor: UUID | None = None,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, object]:
        # Existing audit RLS is owner/admin-only. No steward/own-event grant is added.
        with database.tenant(token(request), organization_id, Capability.MANAGE_MEMBERS) as (c, _):
            c.execute(text("SELECT set_config('statement_timeout','5000',true)"))
            position = None
            if cursor is not None:
                position = (
                    c.execute(
                        text("""SELECT occurred_at,id FROM emailmonitor.audit_events
                    WHERE organization_id=:org AND id=:cursor"""),
                        {"org": organization_id, "cursor": cursor},
                    )
                    .mappings()
                    .first()
                )
                if position is None:
                    raise AuthorizationDenied()
            rows = list(
                c.execute(
                    text("""SELECT id,actor_id,action,resource_id,occurred_at
                FROM emailmonitor.audit_events WHERE organization_id=:org AND
                (CAST(:stamp AS timestamptz) IS NULL OR (occurred_at,id)<
                (CAST(:stamp AS timestamptz),CAST(:last_id AS uuid)))
                ORDER BY occurred_at DESC,id DESC LIMIT :limit"""),
                    {
                        "org": organization_id,
                        "stamp": position["occurred_at"] if position else None,
                        "last_id": position["id"] if position else None,
                        "limit": limit + 1,
                    },
                ).mappings()
            )
            return {
                "organization_id": organization_id,
                "items": [dict(row) for row in rows[:limit]],
                "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
            }

    @router.patch("/organizations/{organization_id}/profile")
    def profile(request: Request, organization_id: UUID, body: ProfileUpdate) -> dict[str, object]:
        # Existing owner-only UPDATE authority; no region, security or lifecycle edit.
        with database.tenant(csrf(request), organization_id, Capability.MANAGE_LIFECYCLE) as (
            c,
            context,
        ):
            c.execute(text("SELECT set_config('statement_timeout','5000',true)"))
            revision = int(
                c.execute(
                    text("""SELECT row_version FROM emailmonitor.organizations
                WHERE id=:org FOR UPDATE"""),
                    {"org": organization_id},
                ).scalar_one()
            )
            if revision != body.expected_revision:
                raise HTTPException(409, "Organization revision conflict")
            row = (
                c.execute(
                    text("""UPDATE emailmonitor.organizations
                SET display_name=:name,timezone=:zone WHERE id=:org
                RETURNING id,display_name,status,region,timezone,row_version"""),
                    {"org": organization_id, "name": body.display_name, "zone": body.timezone},
                )
                .mappings()
                .one()
            )
            audit(c, context, "organization.profile_updated", organization_id)
            return dict(row)

    return router
