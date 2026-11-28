"""Register synthetic Open Access JATS fixtures and the jats_xml route (OA-029)."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0027_open_access_fixture"
down_revision = "0026_bound_reuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Retained Open Access observations require forward repair or a restore")
