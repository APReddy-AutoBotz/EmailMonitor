"""Durable synthetic extraction execution, metadata replay and current lease fencing."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0007_progress"
down_revision = "0006_associations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive progress rollback unsupported; use forward repair")
