"""Pure privacy grammar and fixed metadata limits; no deletion or access grants."""

from uuid import uuid4

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.lifecycle.errors import lifecycle_denied
from emailmonitor.lifecycle.models import (
    Retention,
    SupportCreate,
    SuppressionCreate,
    canonical_privacy,
)
from emailmonitor.lifecycle.service import Lifecycle
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("source", "synthetic-publisher", "synthetic-publisher"),
        ("source", "SYNTHETIC-PUBLISHER", "synthetic-publisher"),
        ("contact", "Mira.Rao@Example.ORG", "mira.rao@example.org"),
        ("domain", "Example.ORG", "example.org"),
    ],
)
def test_privacy_canonicalization_is_conservative_matching_not_identity(
    kind: str, value: str, expected: str
) -> None:
    assert canonical_privacy(kind, value) == expected


@pytest.mark.parametrize(
    "kind,value",
    [
        ("contact", "mira@"),
        ("contact", "mira@example.org\n"),
        ("contact", "mira@exämple.org"),
        ("contact", "mira\u202e@example.org"),
        ("contact", "a..b@example.org"),
        ("contact", "a" * 65 + "@example.org"),
        ("domain", "-example.org"),
        ("domain", "example.org/other"),
        ("domain", "example.org."),
        ("source", "live-publisher"),
        ("person", "Mira Rao"),
        ("job", "arbitrary"),
    ],
)
def test_unsupported_privacy_forms_refuse(kind: str, value: str) -> None:
    with pytest.raises(ValueError):
        canonical_privacy(kind, value)


def test_privacy_value_is_not_in_repr_and_extra_grants_refuse() -> None:
    request = SuppressionCreate(kind="contact", value="mira@example.org", reason="privacy_request")
    assert "mira" not in repr(request)
    with pytest.raises(ValidationError):
        SuppressionCreate.model_validate({**request.model_dump(), "grant_source_access": True})


@pytest.mark.parametrize(
    "field,value",
    [
        ("contact_days", 91),
        ("raw_hours", 25),
        ("export_hours", 25),
        ("excerpt_days", 31),
        ("audit_days", 366),
        ("audit_days", 0),
        ("contact_days", True),
    ],
)
def test_platform_retention_ceiling_never_expands(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Retention.model_validate({field: value})


@pytest.mark.parametrize("minutes", [0, 241, True])
def test_support_context_maximum_is_four_hours_and_not_a_new_role(minutes: object) -> None:
    with pytest.raises(ValidationError):
        SupportCreate.model_validate(
            {
                "grantee_id": uuid4(),
                "job_id": uuid4(),
                "minutes": minutes,
                "reason": "synthetic_incident",
            }
        )


def test_only_exact_private_denial_is_sanitized() -> None:
    error = DBAPIError(
        "private sql", {}, Exception({"C": "EM014", "M": "PRIVACY_SUPPRESSED"}), False
    )
    assert lifecycle_denied(error)
    assert not lifecycle_denied(
        DBAPIError("sql", {}, Exception({"C": "EM014", "M": "different"}), False)
    )
    assert not lifecycle_denied(
        DBAPIError("sql", {}, Exception({"C": "42P01", "M": "missing"}), False)
    )


def test_lifecycle_cannot_activate_in_production() -> None:
    with pytest.raises(IsolationUnavailable):
        Lifecycle(None, "unused", Settings())  # type: ignore[arg-type]


def test_identifier_only_broker_message_cannot_carry_content_or_another_tenant() -> None:
    from emailmonitor.lifecycle.broker import LifecycleEvent, process

    org, event = uuid4(), uuid4()
    value = LifecycleEvent(organization_id=org, event_id=event)
    assert set(value.model_dump()) == {"organization_id", "event_id", "kind"}
    with pytest.raises(ValidationError):
        LifecycleEvent.model_validate({**value.model_dump(), "email": "mira@example.org"})
    with pytest.raises(ValueError, match="scope"):
        process(None, uuid4(), value.model_dump(mode="json"))  # type: ignore[arg-type]


def test_migration_keeps_privacy_indexes_private_and_purge_capability_unforgeable() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0011_lifecycle.sql"
    ).read_text()
    assert "lifecycle_purge_context" in source and "transaction_id=txid_current()" in source
    assert "DISABLE TRIGGER" not in source and "BYPASSRLS" not in source
    assert "digest bytea NOT NULL CHECK(octet_length(digest)=32)" in source
    assert (
        "raw_address text" not in source
        and "GRANT SELECT ON emailmonitor.privacy_keys" not in source
    )
    assert "RFC2104 HMAC-SHA256" in source
    assert "ORDER BY id LIMIT 10" in source and "LIMIT 10" in source


def test_source_release_fences_organization_before_nested_mutex() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0011_lifecycle.sql"
    ).read_text()
    for name in ("source_resource_claim", "source_resource_finish"):
        body = source.split("CREATE OR REPLACE FUNCTION emailmonitor." + name + "(", 1)[1].split(
            "END $$;", 1
        )[0]
        assert body.index("organizations WHERE id=p_org FOR SHARE NOWAIT") < body.index(
            "admission_mutex WHERE id FOR UPDATE"
        )
        assert "EXCEPTION WHEN lock_not_available" in body
    body = source.split("CREATE OR REPLACE FUNCTION emailmonitor.network_entitlement_allowed(", 1)[
        1
    ].split("END $$;", 1)[0]
    assert body.index("organizations WHERE id=p_org FOR SHARE NOWAIT") < body.index(
        "privacy_source_allowed(p_org)"
    )
    assert "EXCEPTION WHEN lock_not_available THEN RETURN false" in body
