"""Create a synthetic login only inside the documented disposable CI database."""

import os

from sqlalchemy import create_engine, text

EXPECTED = "postgresql+pg8000://postgres:emailmonitor-ci-only@127.0.0.1:5432/postgres"
url = os.environ.get("EM_TEST_ADMIN_DATABASE_URL")
if os.environ.get("GITHUB_ACTIONS") != "true" or url != EXPECTED:
    raise RuntimeError("This helper is restricted to the exact disposable CI service")
engine = create_engine(url, hide_parameters=True)
with engine.begin() as connection:
    connection.execute(
        text(
            "CREATE ROLE em_ci_runtime LOGIN NOSUPERUSER NOBYPASSRLS "
            "PASSWORD 'emailmonitor-ci-runtime-only' IN ROLE emailmonitor_runtime"
        )
    )
    connection.execute(
        text(
            "CREATE ROLE em_ci_authenticator LOGIN NOSUPERUSER NOBYPASSRLS "
            "PASSWORD 'emailmonitor-ci-auth-only' IN ROLE emailmonitor_authenticator"
        )
    )
engine.dispose()
