"""Pure bounded configuration tests; no admission/usage implementation claim."""

from uuid import uuid4

import pytest
from emailmonitor.administration.models import (
    Branding,
    Configuration,
    ConfigurationUpdate,
    Entitlements,
    ResourceUsage,
    effective_article_cap,
)
from pydantic import ValidationError


def test_entitlement_intersection_never_expands_source_or_job_ceiling() -> None:
    assert effective_article_cap(Entitlements(), 20, 100) == 20
    assert effective_article_cap(Entitlements(max_articles_per_job=10), 20, 100) == 10
    assert effective_article_cap(Entitlements(max_articles_per_job=0), 20, 100) == 0
    assert effective_article_cap(Entitlements(), 500, 2) == 2


@pytest.mark.parametrize("source,requested", [(True, 20), (20, True), (0, 20), (501, 20), (20, 0)])
def test_invalid_effective_bounds_refuse(source: object, requested: object) -> None:
    with pytest.raises(ValueError):
        effective_article_cap(Entitlements(), source, requested)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [
        {"max_running_jobs": 3},
        {"max_parallel_parse": 3},
        {"max_parallel_export": 2},
        {"max_parallel_browser": 2},
        {"max_articles_per_job": 501},
        {"monthly_resolution_units": 5001},
        {"max_export_bytes": 8388609},
        {"browser_enabled": "true"},
        {"tls_verification": False},
        {"allowed_hosts": ["arbitrary.example"]},
        {"source_min_interval": 0},
        {"payment_token": "unrecognized"},
    ],
)
def test_plan_cannot_expand_platform_or_change_source_security(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Entitlements.model_validate(change)


@pytest.mark.parametrize("label", [" ", "private\ntext", "embedded\x85text", "format\u202etext"])
def test_branding_controls_refuse(label: str) -> None:
    with pytest.raises(ValidationError):
        Branding(label=label)


@pytest.mark.parametrize("color", ["red", "#ABCDEF", "url(external)", "#123456;anything"])
def test_brand_color_is_literal_only(color: str) -> None:
    with pytest.raises(ValidationError):
        Branding(accent_color=color)


def test_configuration_has_no_payment_or_support_access_mutation() -> None:
    config = Configuration(
        organization_id=uuid4(),
        revision=1,
        entitlements=Entitlements(),
        branding=Branding(label="Authored fixture organization"),
        support_reference=uuid4(),
    )
    assert not config.billing_implemented and not config.exceptional_support_grants_available
    assert config.deployment_mode == "synthetic_offline"
    with pytest.raises(ValidationError):
        ConfigurationUpdate.model_validate(
            {"expected_revision": 1, "support_reference": str(uuid4())}
        )
    with pytest.raises(ValidationError):
        Branding(logo_reference="https://arbitrary.example/logo")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["billing_implemented", "exceptional_support_grants_available"])
def test_availability_claims_reject_integer_false(field: str) -> None:
    values = Configuration(
        organization_id=uuid4(),
        revision=1,
        entitlements=Entitlements(),
        branding=Branding(),
        support_reference=uuid4(),
    ).model_dump()
    values[field] = 0
    with pytest.raises(ValidationError):
        Configuration.model_validate(values)


@pytest.mark.parametrize(
    "name,model",
    [
        ("tenant-configuration", Configuration),
        ("tenant-configuration-update", ConfigurationUpdate),
        ("resource-usage", ResourceUsage),
    ],
)
def test_configuration_schema_runtime_examples(
    name: str, model: type[Configuration] | type[ConfigurationUpdate] | type[ResourceUsage]
) -> None:
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3]
    raw = (root / f"contracts/examples/{name}.json").read_text()
    schema = json.loads((root / f"contracts/{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(raw))
    model.model_validate_json(raw)


@pytest.mark.parametrize("counter", [True, -1, 10001, "1"])
def test_usage_counter_refuses_invalid_values(counter: object) -> None:
    import json
    from pathlib import Path

    value = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/examples/resource-usage.json").read_text()
    )
    value["active_units"] = {"parse": counter}
    with pytest.raises(ValidationError):
        ResourceUsage.model_validate_json(json.dumps(value))


def test_usage_unknown_pool_and_false_claims_refuse() -> None:
    import json
    from pathlib import Path

    value = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/examples/resource-usage.json").read_text()
    )
    for change in (
        {"waiting_units": {"unknown": 1}},
        {"billing_implemented": True},
        {"synthetic_only": False},
    ):
        with pytest.raises(ValidationError):
            ResourceUsage.model_validate_json(json.dumps({**value, **change}))
