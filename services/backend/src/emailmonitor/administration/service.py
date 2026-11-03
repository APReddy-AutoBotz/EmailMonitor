"""Current-tenant configuration boundary; shared admission implementation follows."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.administration.models import Configuration, ConfigurationUpdate, ResourceUsage
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.runtime.access import WorkAuthority, WorkDatabase


def administration_denied(error: DBAPIError) -> bool:
    args = getattr(error.orig, "args", ())
    detail = args[0] if args else None
    return isinstance(detail, dict) and (detail.get("C"), detail.get("M")) in {
        ("EM013", "ADMINISTRATION_SCOPE_DENIED"),
        ("EM013", "FIXTURE_ADMISSION_FENCE"),
        ("EM006", "DISCOVERY_POLICY_FENCE"),
        ("EM010", "EXECUTION_WORK_FENCE"),
    }


class Administration:
    def __init__(self, database: WorkDatabase, token: WorkAuthority, settings: Settings) -> None:
        require_fixture(settings)
        self.database, self.token = database, token

    @contextmanager
    def _tenant(self, organization: UUID, capability: Capability) -> Iterator[Connection]:
        try:
            with self.database.tenant(self.token, organization, capability) as (connection, _):
                connection.execute(text("SELECT set_config('statement_timeout','5000',true)"))
                yield connection
        except DBAPIError as error:
            if administration_denied(error):
                raise AuthorizationDenied() from error
            raise

    def read(self, organization: UUID) -> Configuration:
        with self._tenant(organization, Capability.READ_ORGANIZATION) as connection:
            value: object = connection.execute(
                text("SELECT emailmonitor.administration_read(:organization)"),
                {"organization": organization},
            ).scalar_one()
            return Configuration.model_validate_json(json.dumps(value))

    def usage(self, organization: UUID) -> ResourceUsage:
        with self._tenant(organization, Capability.READ_ORGANIZATION) as connection:
            value: object = connection.execute(
                text("SELECT emailmonitor.administration_usage(:organization)"),
                {"organization": organization},
            ).scalar_one()
            return ResourceUsage.model_validate_json(json.dumps(value))

    def update(self, organization: UUID, body: ConfigurationUpdate) -> Configuration:
        payload = {
            "entitlements": body.entitlements.model_dump(mode="json"),
            "branding": body.branding.model_dump(mode="json"),
        }
        with self._tenant(organization, Capability.MANAGE_LIFECYCLE) as connection:
            value: object = connection.execute(
                text(
                    """SELECT emailmonitor.administration_update(
:organization,:revision,CAST(:configuration AS jsonb),:event)"""
                ),
                {
                    "organization": organization,
                    "revision": body.expected_revision,
                    "configuration": json.dumps(payload),
                    "event": uuid4(),
                },
            ).scalar_one()
            return Configuration.model_validate_json(json.dumps(value))
