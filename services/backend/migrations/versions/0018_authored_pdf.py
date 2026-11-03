"""Opt-in durable authored PDF observations, without network or role grants."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0018_authored_pdf"
down_revision = "0017_execution_receipt_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Authored PDF persistence requires forward repair")
