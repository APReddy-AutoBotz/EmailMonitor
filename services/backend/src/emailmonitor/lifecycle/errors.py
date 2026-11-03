"""Exact private lifecycle denial codes; arbitrary SQL failures remain errors."""

from sqlalchemy.exc import DBAPIError


def lifecycle_denied(error: DBAPIError) -> bool:
    original = error.orig
    args = getattr(original, "args", ())
    detail = args[0] if args else None
    code = getattr(original, "sqlstate", None) or (
        detail.get("C") if isinstance(detail, dict) else None
    )
    reason = getattr(original, "message", None) or (
        detail.get("M") if isinstance(detail, dict) else None
    )
    return (code, reason) in {
        ("EM014", "LIFECYCLE_SCOPE_DENIED"),
        ("EM014", "LIFECYCLE_PURGE_FENCE"),
        ("EM014", "PRIVACY_SUPPRESSED"),
    }
