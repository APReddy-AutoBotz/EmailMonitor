"""Closed installed fixture routing; SQL authority and actual execution are separate gates."""

from typing import Literal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from emailmonitor.extraction.pdf_fixture import DIGESTS
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings
from emailmonitor.sources.provider_documents import URLS

Profile = Literal["authored-html-service-reference", "controlled-xml-service-reference"]
ORG, WORKER, PUBLISHER, JOB = (UUID(int=value) for value in range(1, 5))


def bindings(profile: Profile) -> ServiceBindings:
    return ServiceBindings(
        profile=profile,
        tenants=(ServiceBinding(organization=ORG, worker=WORKER, publisher=PUBLISHER, seconds=60),),
    )


def connection(url: str) -> MagicMock:
    result = MagicMock()
    result.execute.return_value.scalar_one_or_none.return_value = url
    return result


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_composed_pdf_fixture_binding_uses_exact_existing_principals(name: str) -> None:
    c = connection("https://synthetic.publisher.example/" + name)
    bindings("controlled-xml-service-reference").issue(c, ORG, JOB, "extraction")
    assert c.execute.call_count == 3
    calls = c.execute.call_args_list[1:]
    for call, principal in zip(calls, (WORKER, PUBLISHER), strict=True):
        assert "emailmonitor.delegate_service_work(" in str(call.args[0])
        assert call.args[1] == {
            "org": ORG,
            "principal": principal,
            "resource": JOB,
            "purpose": "extraction",
            "seconds": 60,
        }


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_default_html_binding_still_refuses_every_pdf_before_delegation(name: str) -> None:
    c = connection("https://synthetic.publisher.example/" + name)
    with pytest.raises(AuthorizationDenied):
        bindings("authored-html-service-reference").issue(c, ORG, JOB, "extraction")
    assert c.execute.call_count == 1


@pytest.mark.parametrize(
    "profile", ["authored-html-service-reference", "controlled-xml-service-reference"]
)
@pytest.mark.parametrize(
    "url",
    [
        "https://synthetic.publisher.example/unknown.pdf",
        "https://synthetic.publisher.example/article-a.pdf?download=1",
        "https://synthetic.publisher.example/article-a.pdf#page=2",
        "https://synthetic.publisher.example/%61rticle-a.pdf",
        "https://publisher.example/article-a.pdf",
        "file:///article-a.pdf",
    ],
)
def test_pdf_binding_does_not_admit_arbitrary_or_modified_urls(profile: Profile, url: str) -> None:
    c = connection(url)
    with pytest.raises(AuthorizationDenied):
        bindings(profile).issue(c, ORG, JOB, "extraction")
    assert c.execute.call_count == 1


@pytest.mark.parametrize("url", sorted(URLS))
def test_existing_controlled_xml_routes_remain_unchanged(url: str) -> None:
    c = connection(url)
    bindings("controlled-xml-service-reference").issue(c, ORG, JOB, "extraction")
    assert c.execute.call_count == 3
    c.reset_mock()
    with pytest.raises(AuthorizationDenied):
        bindings("authored-html-service-reference").issue(c, ORG, JOB, "extraction")
    assert c.execute.call_count == 1


@pytest.mark.parametrize("failed_principal", [0, 1])
def test_pdf_route_never_catches_or_retries_sql_authority_refusal(failed_principal: int) -> None:
    c = connection("https://synthetic.publisher.example/article-a.pdf")
    selected = c.execute.return_value
    c.execute.side_effect = [selected, *([None] * failed_principal), AuthorizationDenied()]
    with pytest.raises(AuthorizationDenied):
        bindings("controlled-xml-service-reference").issue(c, ORG, JOB, "extraction")
    assert c.execute.call_count == 2 + failed_principal


def test_pdf_route_requires_existing_explicit_tenant_binding() -> None:
    c = connection("https://synthetic.publisher.example/article-a.pdf")
    with pytest.raises(ValueError, match="Explicit service binding required"):
        bindings("controlled-xml-service-reference").issue(c, UUID(int=99), JOB, "extraction")
    c.execute.assert_not_called()
