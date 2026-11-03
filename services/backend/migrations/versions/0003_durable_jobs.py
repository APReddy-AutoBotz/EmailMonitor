"""Durable offline job ledger and transactional outbox."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0003_durable_jobs"
down_revision = "0002_source_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive job/usage/outbox rollback is unsupported; use forward repair")
