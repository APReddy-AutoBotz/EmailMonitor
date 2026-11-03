"""Forward-only synthetic XML integration preserving lifecycle fences."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0012_xml_pipeline"
down_revision = "0011_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("XML retained state requires forward repair; no destructive downgrade")
