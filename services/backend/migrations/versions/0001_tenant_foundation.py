"""Organization identity, sessions and forced tenant RLS."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0001_tenant_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError(
        "Destructive identity/audit rollback is unsupported; use reviewed forward repair"
    )
