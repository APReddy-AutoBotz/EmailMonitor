"""Synthetic shared admission and usage; no external access or billing."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0010_administration"
down_revision = "0009_operator_ui"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive administration rollback unsupported; use forward repair")
