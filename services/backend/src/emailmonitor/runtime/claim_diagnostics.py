"""Closed, synthetic-only publisher claim categories; never retain exception data."""

from sqlalchemy.exc import DBAPIError

from emailmonitor.organizations.database import AuthorizationDenied

OPERATIONS = frozenset(
    {
        "authority_or_cleanup",
        "claim_sql",
        "phase_validation",
        "queue_selection",
        "authority_finalize",
    }
)
PURPOSES = frozenset({"extraction", "export"})
SQLSTATES = {
    "55P03": "sql_55p03",
    "EM017": "sql_em017",
    "42501": "sql_42501",
    "57014": "sql_57014",
    "40P01": "sql_40p01",
    "40001": "sql_40001",
}
CATEGORIES = frozenset({*SQLSTATES.values(), "db_other", "db_unknown", "non_db"})


def claim_receipt(error: Exception, operation: object, purpose: object) -> str | None:
    """Classify one immediate DBAPI failure without recording SQL or error text."""
    if type(operation) is not str or operation not in OPERATIONS:
        return None
    if type(purpose) is not str or purpose not in PURPOSES:
        return None
    failure: BaseException | None = error
    if type(error) is AuthorizationDenied and error.__suppress_context__:
        failure = error.__context__ if isinstance(error.__context__, DBAPIError) else error
    category = "non_db"
    if isinstance(failure, DBAPIError):
        category = "db_unknown"
        original = failure.orig
        if original is not None and original.args and type(original.args[0]) is dict:
            code = original.args[0].get("C")
            if type(code) is str and len(code) == 5 and code.isascii() and code.isalnum():
                category = SQLSTATES.get(code, "db_other")
    return f"{operation}.{category}.{purpose}"


def valid_claim_receipt(value: object) -> bool:
    if type(value) is not str:
        return False
    fields = value.split(".")
    return (
        len(fields) == 3
        and fields[0] in OPERATIONS
        and fields[1] in CATEGORIES
        and fields[2] in PURPOSES
    )
