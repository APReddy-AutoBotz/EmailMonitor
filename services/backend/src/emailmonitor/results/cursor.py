"""Canonical keyset navigation binds tenant, kind and filters; it grants no authority."""

import base64
import hashlib
import json
from typing import Literal
from uuid import UUID

from emailmonitor.results.models import Filters

Kind = Literal["contacts", "outcomes"]


def fingerprint(filters: Filters) -> str:
    return hashlib.sha256(filters.model_dump_json().encode()).hexdigest()


def encode(org: UUID, kind: Kind, filters: Filters, first: UUID, second: UUID) -> str:
    document = [1, str(org), kind, fingerprint(filters), str(first), str(second)]
    raw = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(org: UUID, kind: Kind, filters: Filters, cursor: str | None) -> tuple[UUID, UUID] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
        raise ValueError("Bounded tenant/filter cursor required")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if (
            not isinstance(value, list)
            or len(value) != 6
            or type(value[0]) is not int
            or value[:4] != [1, str(org), kind, fingerprint(filters)]
            or not all(isinstance(part, str) for part in value[4:])
        ):
            raise ValueError("Cursor scope mismatch")
        first, second = UUID(value[4]), UUID(value[5])
        if encode(org, kind, filters, first, second) != cursor:
            raise ValueError("Noncanonical cursor")
        return first, second
    except (UnicodeError, ValueError, TypeError) as error:
        raise ValueError("Invalid tenant/filter cursor") from error
