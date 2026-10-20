"""Bounded service authority; no credentials or automatic historical grants."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0014_service_authority"
down_revision = "0013_provider_journey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Service revocation history requires forward repair")
