"""Enable the source-bound retained reuse candidate after the 0022 guards."""

from alembic import op

revision = "0023_enable_retained_reuse"
down_revision = "0022_retained_reuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE emailmonitor_owner")
    op.execute(
        "ALTER TABLE emailmonitor.article_observations DROP CONSTRAINT retained_reuse_disabled"
    )
    op.execute("""
CREATE OR REPLACE FUNCTION emailmonitor.service_schema_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,emailmonitor AS $$
 SELECT (SELECT count(*)=1 AND min(version_num)='0023_enable_retained_reuse'
 FROM public.alembic_version)
$$
""")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("Retained reuse data requires forward repair or a controlled restore")
