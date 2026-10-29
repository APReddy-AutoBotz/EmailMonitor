"""Admit only verified original-bound authored XML/PDF reuse."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0026_bound_reuse"
down_revision = "0025_staged_bound_reuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Retained reuse lineage requires forward repair or a controlled restore")
