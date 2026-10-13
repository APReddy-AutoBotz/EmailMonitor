"""Evidence-backed synthetic associations and role-scoped optimistic review."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0006_associations"
down_revision = "0005_article_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive association rollback unsupported; use forward repair")
