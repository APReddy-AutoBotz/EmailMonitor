"""Give Europe PMC its own fixture-only catalog source (OA-030, document 92)."""

from pathlib import Path

import sqlparse
from alembic import op

revision = "0028_europe_pmc_source"
down_revision = "0027_open_access_fixture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in sqlparse.split(Path(__file__).with_suffix(".sql").read_text()):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Europe PMC observations under widened source CHECKs require forward repair")
