"""Draft extraction requests and authorized durable controls; planning remains gated."""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import text

from emailmonitor.config import Settings
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest, StrictModel
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.organizations.roles import Capability


class Revision(StrictModel):
    expected_revision: int = Field(ge=1)


def job_router(
    database: Database,
    token: Callable[[Request], str],
    csrf: Callable[[Request], str],
    settings: Settings,
) -> APIRouter:
    router = APIRouter()

    @router.post("/organizations/{organization_id}/jobs", status_code=201)
    def create(request: Request, organization_id: UUID, body: JobRequest) -> dict[str, object]:
        key = request.headers.get("Idempotency-Key", "")
        try:
            job = Ledger(database, csrf(request), settings).create(organization_id, body, key)
        except ValueError as error:
            raise HTTPException(422, "Bounded Idempotency-Key required") from error
        return {
            "id": str(job),
            "state": "draft",
            "planning_available": False,
            "extraction_implemented": False,
        }

    @router.get("/organizations/{organization_id}/jobs")
    def jobs(request: Request, organization_id: UUID) -> list[dict[str, object]]:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            return [
                dict(r)
                for r in c.execute(
                    text("""SELECT id,kind,state,generation,row_version,
discovery_complete,created_at FROM emailmonitor.jobs WHERE organization_id=:org
ORDER BY created_at DESC LIMIT 100"""),
                    {"org": organization_id},
                ).mappings()
            ]

    @router.get("/organizations/{organization_id}/jobs/{job_id}")
    def job(request: Request, organization_id: UUID, job_id: UUID) -> dict[str, object]:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            row = (
                c.execute(
                    text("SELECT * FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
                    {"org": organization_id, "job": job_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AuthorizationDenied()
            result = dict(row)
            result["counts"] = {
                str(r["state"]): int(r["count"])
                for r in c.execute(
                    text("""SELECT state,count(*) AS count FROM emailmonitor.job_items
WHERE organization_id=:org AND job_id=:job GROUP BY state"""),
                    {"org": organization_id, "job": job_id},
                ).mappings()
            }
            return result

    @router.get("/organizations/{organization_id}/jobs/{job_id}/items")
    def items(request: Request, organization_id: UUID, job_id: UUID) -> list[dict[str, object]]:
        with database.tenant(token(request), organization_id, Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            rows = c.execute(
                text("""SELECT id,state,attempts,result FROM emailmonitor.job_items
WHERE organization_id=:org AND job_id=:job ORDER BY id LIMIT 100"""),
                {"org": organization_id, "job": job_id},
            ).mappings()
            return [dict(r) for r in rows]

    @router.post("/organizations/{organization_id}/jobs/{job_id}/{action}")
    def control(
        request: Request, organization_id: UUID, job_id: UUID, action: str, body: Revision
    ) -> dict[str, bool]:
        if action not in {"pause", "resume", "cancel"}:
            raise HTTPException(
                409, "Planning, start and continuation are unavailable until EM-006"
            )
        Ledger(database, csrf(request), settings).control(
            organization_id, job_id, action, body.expected_revision
        )
        return {"updated": True}

    return router
