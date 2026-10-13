"""Short current-authorized synthetic lifecycle transactions; no content in receipts."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.lifecycle.errors import lifecycle_denied
from emailmonitor.lifecycle.models import (
    DeletionReceipt,
    DeletionRequest,
    RetentionState,
    RetentionUpdate,
    SupportContext,
    SupportCreate,
    SupportInspection,
    Suppression,
    SuppressionCreate,
    canonical_privacy,
)
from emailmonitor.organizations.database import AuthorizationDenied, Database, RevisionConflict
from emailmonitor.organizations.roles import Capability

Model = TypeVar("Model", bound=BaseModel)


class Lifecycle:
    def __init__(self, database: Database, token: str, settings: Settings) -> None:
        require_fixture(settings)
        self.database, self.token = database, token

    @contextmanager
    def _tenant(self, org: UUID, capability: Capability) -> Iterator[Connection]:
        try:
            with self.database.tenant(self.token, org, capability) as (connection, _):
                connection.execute(text("SELECT set_config('statement_timeout','5000',true)"))
                yield connection
        except DBAPIError as error:
            args = getattr(error.orig, "args", ())
            detail = args[0] if args else None
            if isinstance(detail, dict) and (detail.get("C"), detail.get("M")) == (
                "EM014",
                "LIFECYCLE_REVISION_CONFLICT",
            ):
                raise RevisionConflict() from None
            if lifecycle_denied(error):
                raise AuthorizationDenied() from None
            raise

    def _call(
        self,
        org: UUID,
        capability: Capability,
        statement: str,
        parameters: dict[str, Any],
        model: type[Model],
    ) -> Model:
        with self._tenant(org, capability) as connection:
            value: object = connection.execute(
                text(statement), {"org": org, **parameters}
            ).scalar_one()
            if value is None:
                raise AuthorizationDenied()
            return model.model_validate_json(json.dumps(value))

    def retention(self, org: UUID) -> RetentionState:
        return self._call(
            org,
            Capability.MANAGE_LIFECYCLE,
            "SELECT emailmonitor.lifecycle_retention(:org)",
            {},
            RetentionState,
        )

    def update_retention(self, org: UUID, body: RetentionUpdate) -> RetentionState:
        return self._call(
            org,
            Capability.MANAGE_LIFECYCLE,
            "SELECT emailmonitor.lifecycle_retention_update("
            ":org,:revision,CAST(:retention AS jsonb))",
            {"revision": body.expected_revision, "retention": body.retention.model_dump_json()},
            RetentionState,
        )

    def suppress(self, org: UUID, body: SuppressionCreate) -> Suppression:
        return self._call(
            org,
            Capability.MANAGE_SOURCE_POLICY,
            "SELECT emailmonitor.lifecycle_suppress(:org,:id,:kind,:value,:reason)",
            {
                "id": uuid4(),
                "kind": body.kind,
                "value": canonical_privacy(body.kind, body.value),
                "reason": body.reason,
            },
            Suppression,
        )

    def withdraw(self, org: UUID, identifier: UUID) -> Suppression:
        return self._call(
            org,
            Capability.MANAGE_SOURCE_POLICY,
            "SELECT emailmonitor.lifecycle_withdraw(:org,:id)",
            {"id": identifier},
            Suppression,
        )

    def stage(self, org: UUID, body: DeletionRequest) -> DeletionReceipt:
        return self._call(
            org,
            Capability.MANAGE_LIFECYCLE,
            "SELECT emailmonitor.lifecycle_stage(:org,:id,:job,:reason)",
            {"id": uuid4(), "job": body.job_id, "reason": body.reason},
            DeletionReceipt,
        )

    def purge(self, org: UUID, identifier: UUID) -> DeletionReceipt:
        return self._call(
            org,
            Capability.MANAGE_LIFECYCLE,
            "SELECT emailmonitor.lifecycle_purge(:org,:id)",
            {"id": identifier},
            DeletionReceipt,
        )

    def tick(self, org: UUID) -> int:
        with self._tenant(org, Capability.MANAGE_LIFECYCLE) as connection:
            value: object = connection.execute(
                text("SELECT emailmonitor.lifecycle_tick(:org)"), {"org": org}
            ).scalar_one()
            if type(value) is not int or not 0 <= value <= 10:
                raise RuntimeError("Invalid bounded lifecycle count")
            return value

    def approve_support(self, org: UUID, body: SupportCreate) -> SupportContext:
        return self._call(
            org,
            Capability.MANAGE_LIFECYCLE,
            "SELECT emailmonitor.lifecycle_support_create(:org,:id,:grantee,:job,:minutes,:reason)",
            {
                "id": uuid4(),
                "grantee": body.grantee_id,
                "job": body.job_id,
                "minutes": body.minutes,
                "reason": body.reason,
            },
            SupportContext,
        )

    def revoke_support(self, org: UUID, identifier: UUID) -> SupportContext:
        return self._call(
            org,
            Capability.MANAGE_LIFECYCLE,
            "SELECT emailmonitor.lifecycle_support_revoke(:org,:id)",
            {"id": identifier},
            SupportContext,
        )

    def inspect_support(self, org: UUID, identifier: UUID) -> SupportInspection:
        return self._call(
            org,
            Capability.READ_ORGANIZATION,
            "SELECT emailmonitor.lifecycle_support_inspect(:org,:id)",
            {"id": identifier},
            SupportInspection,
        )

    def schedule(self, org: UUID) -> tuple[UUID, ...]:
        with self._tenant(org, Capability.MANAGE_LIFECYCLE) as connection:
            return tuple(
                UUID(str(row[0]))
                for row in connection.execute(
                    text("SELECT id FROM emailmonitor.lifecycle_schedule(:org,:id)"),
                    {"org": org, "id": uuid4()},
                )
            )

    def scheduled_tick(self, org: UUID, event: UUID) -> int:
        with self._tenant(org, Capability.MANAGE_LIFECYCLE) as connection:
            value: object = connection.execute(
                text("SELECT emailmonitor.lifecycle_scheduled_tick(:org,:id)"),
                {"org": org, "id": event},
            ).scalar_one()
            if type(value) is not int or not 0 <= value <= 10:
                raise RuntimeError("Invalid bounded lifecycle count")
            return value

    def confirmed(self, org: UUID, event: UUID) -> None:
        with self._tenant(org, Capability.MANAGE_LIFECYCLE) as connection:
            connection.execute(
                text("SELECT emailmonitor.lifecycle_confirmed(:org,:id)"), {"org": org, "id": event}
            )
