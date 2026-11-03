"""Audited unlink of a retained association without deleting source evidence."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0021_review_unlink"
down_revision = "0020_retained_source_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Unlink audit history requires forward repair or a controlled restore")
