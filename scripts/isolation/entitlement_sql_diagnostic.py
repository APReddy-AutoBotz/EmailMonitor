"""Temporary fixed-category instrumentation in the owned disposable SQL fixture."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

BODY_SHA256 = "f817066e44d4aa901864147d30ff4610e82932bde3ff9a20cfcf6c1fa935c77d"
SIGNATURE = "emailmonitor.network_entitlement_allowed(uuid,text,uuid)"
NOTICE = "EM_UI_ENTITLEMENT_V1 "


def instrument(body: str) -> str:
    if hashlib.sha256(body.encode()).hexdigest() != BODY_SHA256:
        raise RuntimeError("Exact owned entitlement predicate required")
    value = body.replace(
        "DECLARE conf jsonb; saved jsonb;",
        "DECLARE conf jsonb; saved jsonb; diagnostic_allowed boolean;",
        1,
    )
    # The expression is evaluated once, with its original NULL/boolean result.
    value = value.replace(" RETURN conf IS NOT NULL", " diagnostic_allowed := conf IS NOT NULL", 1)
    value = value.replace(
        "EXCEPTION WHEN lock_not_available THEN RETURN false;",
        "IF diagnostic_allowed IS TRUE THEN\n"
        f" RAISE NOTICE '{NOTICE}allowed';\nELSE\n"
        f" RAISE NOTICE '{NOTICE}authority_denied';\nEND IF;\n"
        "RETURN diagnostic_allowed;\n"
        "EXCEPTION WHEN lock_not_available THEN\n"
        f" RAISE NOTICE '{NOTICE}lock_refused'; RETURN false;",
        1,
    )
    # Only the five pre-existing ordinary refusal returns receive this label.
    prefix, exception = value.split("EXCEPTION WHEN lock_not_available", 1)
    if prefix.count("RETURN false;") != 5:
        raise RuntimeError("Unexpected entitlement refusal structure")
    return (
        prefix.replace("RETURN false;", f"RAISE NOTICE '{NOTICE}authority_denied'; RETURN false;")
        + "EXCEPTION WHEN lock_not_available"
        + exception
    )


def definition(engine: Engine) -> tuple[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT prosrc,pg_get_functiondef(oid),proconfig,prosecdef,"
                "prorettype::regtype::text "
                "FROM pg_proc WHERE oid=to_regprocedure(:s)"
            ),
            {"s": SIGNATURE},
        ).one()
        if row[2:] != (["search_path=pg_catalog, emailmonitor"], True, "boolean"):
            raise RuntimeError("Unexpected entitlement function configuration")
        # Notices are client-only under this required existing server setting.
        if connection.execute(text("SHOW log_min_messages")).scalar_one() != "warning":
            raise RuntimeError("Owned diagnostic requires server notice logging disabled")
        return str(row[0]), str(row[1])


def ownership(engine: Engine) -> tuple[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT proowner::text,COALESCE(proacl::text,'') FROM pg_proc "
                "WHERE oid=to_regprocedure(:s)"
            ),
            {"s": SIGNATURE},
        ).one()
        return str(row[0]), str(row[1])


@contextmanager
def entitlement_diagnostic(engine: Engine) -> Iterator[None]:
    if engine.url.host != "127.0.0.1" or engine.url.database != "postgres":
        raise RuntimeError("Explicit disposable loopback database required")
    original, sql = definition(engine)
    original_ownership = ownership(engine)
    changed = instrument(original)
    if sql.count(original) != 1:
        raise RuntimeError("Ambiguous entitlement definition")
    with engine.begin() as connection:
        connection.execute(text(sql.replace(original, changed, 1)))
    try:
        current, current_sql = definition(engine)
        if current != changed or current_sql.replace(changed, original, 1) != sql:
            raise RuntimeError("Diagnostic installation changed function attributes")
        if ownership(engine) != original_ownership:
            raise RuntimeError("Diagnostic changed function ownership or privileges")
        yield
    finally:
        current, _ = definition(engine)
        if current != changed:
            raise RuntimeError("Refusing to overwrite changed diagnostic function")
        with engine.begin() as connection:
            connection.execute(text(sql))
        if definition(engine) != (original, sql) or ownership(engine) != original_ownership:
            raise RuntimeError("Original entitlement predicate restore unverified")
