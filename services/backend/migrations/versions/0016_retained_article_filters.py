"""Select exact retained article units without expanding read or execution authority."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0016_retained_article_filters"
down_revision = "0015_service_plan_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Retained filter snapshots require forward repair")
