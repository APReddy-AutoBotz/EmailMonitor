"""Tenant-owned synthetic HTML observations, separate from accepted contacts."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0005_article_observations"
down_revision = "0004_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive observation rollback unsupported; use forward repair")
