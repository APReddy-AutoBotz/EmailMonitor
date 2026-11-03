"""Synthetic filtered results and current-authorized private export snapshots."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0008_results"
down_revision = "0007_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive result/export rollback unsupported; use forward repair")
