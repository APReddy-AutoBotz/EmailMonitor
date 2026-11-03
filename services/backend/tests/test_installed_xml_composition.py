"""Closed installed XML profile admission; no SQL/container success is implied."""

from dataclasses import replace
from typing import Any, cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from api_client import APIClient
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.runtime import service_api, worker
from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings
from emailmonitor.sources.provider_documents import URLS
from pydantic import ValidationError
from sqlalchemy import Connection
from test_service_runtime_controls import APIHarness, configuration
from test_service_runtime_controls import api as api


@pytest.mark.parametrize("route", sorted(URLS))
@pytest.mark.parametrize("enabled", [False, True])
def test_only_explicit_profile_admits_controlled_routes(route: str, enabled: bool) -> None:
    c = MagicMock()
    c.execute.return_value.scalar_one_or_none.return_value = route
    binding = ServiceBinding(organization=UUID(int=1), worker=UUID(int=2), publisher=UUID(int=3))
    bindings = ServiceBindings(
        profile="controlled-xml-service-reference"
        if enabled
        else "authored-html-service-reference",
        tenants=(binding,),
    )
    if enabled:
        bindings.issue(cast(Connection, c), UUID(int=1), UUID(int=4), "extraction")
        assert c.execute.call_count == 3
    else:
        with pytest.raises(AuthorizationDenied):
            bindings.issue(cast(Connection, c), UUID(int=1), UUID(int=4), "extraction")
        assert c.execute.call_count == 1
    assert all("source_policies" not in str(call.args[0]) for call in c.execute.call_args_list)


@pytest.mark.parametrize(
    "route",
    [
        "https://api.elsevier.com/content/article/doi/10.9999/synthetic.1?view=FULL",
        "https://synthetic.publisher.example/article-xml.xml",
        "https://unregistered.example/article",
        None,
    ],
)
def test_controlled_profile_never_broadens_to_legacy_xml_or_live_urls(route: str | None) -> None:
    c = MagicMock()
    c.execute.return_value.scalar_one_or_none.return_value = route
    bindings = ServiceBindings(
        profile="controlled-xml-service-reference",
        tenants=(
            ServiceBinding(organization=UUID(int=1), worker=UUID(int=2), publisher=UUID(int=3)),
        ),
    )
    with pytest.raises(AuthorizationDenied):
        bindings.issue(cast(Connection, c), UUID(int=1), UUID(int=4), "extraction")
    assert c.execute.call_count == 1


def test_runtime_profile_reports_opt_in_without_live_or_production_claims(api: APIHarness) -> None:
    config = replace(
        api.config,
        bindings=api.config.bindings.model_copy(
            update={"profile": "controlled-xml-service-reference"}
        ),
    )
    with service_api.service_api(config, api.provider) as app:
        result = APIClient(app, "https://app.example.test").get("/api/v1/runtime-profile").json()
        assert result == {
            "profile": "controlled-xml-service-reference",
            "production_ready": False,
            "xml_available": True,
            "pdf_available": False,
            "dynamic_browser_available": False,
            "live_sources_available": False,
        }


@pytest.mark.parametrize(
    "profile,descriptor",
    [("authored-html-service-reference", 99), ("controlled-xml-service-reference", None)],
)
def test_profile_and_capability_must_match_before_sql(
    profile: str, descriptor: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Mock()
    monkeypatch.setattr(worker, "ServiceDatabase", database)
    config = worker.ServiceRuntimeConfig.model_validate(
        {**configuration().model_dump(), "profile": profile}
    )
    with pytest.raises(ValueError, match="profile and owned capability"):
        worker.ServiceWorker(config, controlled_channel=cast(Any, descriptor))
    database.assert_not_called()


@pytest.mark.parametrize("profile", ["live", "module:factory", True, None])
def test_profile_is_a_closed_operator_configuration(profile: Any) -> None:
    with pytest.raises(ValidationError):
        worker.ServiceRuntimeConfig.model_validate(
            {**configuration().model_dump(), "profile": profile}
        )
    with pytest.raises(ValidationError):
        ServiceBindings.model_validate({"profile": profile})
