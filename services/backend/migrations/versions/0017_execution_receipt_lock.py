"""Keep execution receipts compatible with current worker authority reads."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0017_execution_receipt_lock"
down_revision = "0016_retained_article_filters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Execution receipt compatibility requires forward repair")
