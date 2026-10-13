"""Forward-only synthetic retention/privacy/deletion foundation."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0011_lifecycle"
down_revision = "0010_administration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Lifecycle tombstones cannot be rolled back; use forward repair")
