"""Migration credentials are separate from the non-owner runtime role."""

import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ.get("EM_MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError(
        "Explicit migration database URL required; runtime credentials are not reused"
    )
engine = create_engine(url, hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
