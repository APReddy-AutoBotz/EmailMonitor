from datetime import UTC, datetime, timedelta

import pytest
from emailmonitor.sources.policy import PolicyProposal, validate_approval
from pydantic import ValidationError
from test_source_foundation import policy_body


@pytest.mark.parametrize(
    "override",
    [
        {"execution_mode": "live"},
        {"allowed_hosts": ["evil.example"]},
        {"credential_reference": "secret-token"},
        {"permission_reference": "https://token.example/?key=x"},
        {"allowed_regions": ["us"]},
        {"robots_handling": "ignore"},
        {"allowed_operations": ["fetch_pdf"]},
        {"allowed_operations": ["search", "search"]},
        {"valid_until": "2026-12-31T00:00:00"},
        {"unknown": True},
        {
            "limits": {
                "max_concurrent_requests": 2,
                "min_request_interval_seconds": 0.1,
                "max_articles_per_job": 10000,
            }
        },
        {"retention": {"raw_hours": 25, "excerpt_days": 30, "contact_days": 90}},
    ],
)
def test_policy_platform_ceiling(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PolicyProposal.model_validate(policy_body(**override))


def test_policy_approval_is_bounded_separate_permission() -> None:
    now = datetime.now(UTC)
    policy = PolicyProposal.model_validate(policy_body())
    validate_approval(policy, now)
    for modified in (
        policy.model_copy(update={"permission_reference": None}),
        policy.model_copy(update={"valid_until": now - timedelta(seconds=1)}),
        policy.model_copy(update={"valid_until": now + timedelta(days=366)}),
    ):
        with pytest.raises(ValueError):
            validate_approval(modified, now)
