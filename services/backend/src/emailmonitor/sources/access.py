"""Current point-in-time policy decision shared by API and fixture gateway."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Connection, text

from emailmonitor.sources.policy import Evaluation, PolicyProposal


def current_policy(connection: Connection, organization: UUID, source: str) -> dict[str, object]:
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


def policy_decision(
    row: dict[str, object], request: Evaluation, now: datetime | None = None
) -> bool:
    policy = PolicyProposal.model_validate(row["policy"])
    support = row["support"]
    routes = support.get("routes_by_operation", {}) if isinstance(support, dict) else {}
    route_allowed = isinstance(routes, dict) and request.path in routes.get(request.operation, [])
    return bool(
        route_allowed
        and row["enabled"] is True
        and row["version"] == request.expected_version
        and row["state"] == "approved"
        and policy.valid_until > (now or datetime.now(UTC))
        and request.execution_mode == "fixture"
        and request.host in policy.allowed_hosts
        and request.operation in policy.allowed_operations
        and (request.operation != "export_contacts" or policy.export_contacts_allowed)
    )
