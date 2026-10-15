"""Forward-only controlled provider journey preserving all latest XML/lifecycle fences."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0013_provider_journey"
down_revision = "0012_xml_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("XML retained state requires forward repair; no destructive downgrade")
