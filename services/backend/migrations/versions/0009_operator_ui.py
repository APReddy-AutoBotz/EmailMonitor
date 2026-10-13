"""Bounded synthetic UI export preview and optional field selection."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0009_operator_ui"
down_revision = "0008_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive operator UI rollback unsupported; use forward repair")
