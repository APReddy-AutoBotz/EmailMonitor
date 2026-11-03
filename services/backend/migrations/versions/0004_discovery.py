"""Tenant-owned offline planning and page checkpoints."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0004_discovery"
down_revision = "0003_durable_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive discovery rollback unsupported; use forward repair")
