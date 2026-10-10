"""Synthetic catalog and versioned tenant source policies."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0002_source_policy"
down_revision = "0001_tenant_foundation"
branch_labels = None

depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError(
        "Destructive policy/audit rollback is unsupported; use reviewed forward repair"
    )
