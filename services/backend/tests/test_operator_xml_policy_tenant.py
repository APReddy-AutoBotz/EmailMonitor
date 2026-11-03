"""XML-profile governance through real ASGI sessions and runtime PostgreSQL roles."""

import pytest
from api_client import APIClient
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.organizations.roles import Capability
from sqlalchemy import text
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

XML_OPERATIONS = ["search", "fetch_xml", "extract_contacts", "retain_excerpt", "export_contacts"]


def xml_policy() -> dict[str, object]:
    return policy_body(
        allowed_operations=XML_OPERATIONS,
        retention={"raw_hours": 0, "excerpt_days": 30, "contact_days": 90},
    )


def headers(scenario: Scenario, client: APIClient, role: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": scenario.login(client, role)}


def propose(client: APIClient, path: str, auth: dict[str, str], version: int = 0) -> None:
    response = client.post(
        path + "/policies",
        headers=auth,
        json={"expected_version": version, "policy": xml_policy()},
    )
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "pending_review"
    assert response.json()["reviewed_by"] is None
    assert response.json()["export_contacts_allowed"] is False


def transition(version: int = 1, revision: int = 1, state: str = "approved") -> dict[str, object]:
    return {"expected_version": version, "expected_revision": revision, "state": state}


def evaluate(client: APIClient, path: str, version: int, operation: str, route: str) -> bool:
    response = client.post(
        path + "/evaluate",
        json={
            "expected_version": version,
            "operation": operation,
            "host": "synthetic.publisher.example",
            "path": route,
            "execution_mode": "fixture",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["execution_available"] is False
    return bool(response.json()["policy_authorized"])


@pytest.mark.parametrize("role", ["owner", "data_steward"])
def test_xml_proposal_requires_separate_exact_version_approval(
    scenario: Scenario, role: str
) -> None:
    with scenario.client() as client:
        auth = headers(scenario, client, role)
        path = source_path(scenario)
        propose(client, path, auth)
        assert not evaluate(client, path, 1, "fetch_xml", "/article-xml.xml")
        # Approval carries only persisted version/revision/state, never a selected UI profile.
        response = client.post(path + "/policy-state", headers=auth, json=transition())
        assert response.status_code == 200, response.text
        approved = response.json()
        assert approved["state"] == "approved" and approved["row_version"] == 2
        assert approved["reviewed_by"] == str(scenario.identities[role])
        assert approved["allowed_operations"] == XML_OPERATIONS
        assert approved["retention"] == {"raw_hours": 0, "excerpt_days": 30, "contact_days": 90}
        assert approved["credential_reference"] is None
        assert approved["allowed_hosts"] == ["synthetic.publisher.example"]
        assert approved["allowed_regions"] == ["test-only"]
        assert approved["execution_mode"] == "fixture"
        assert approved["export_contacts_allowed"] is True
        for operation in XML_OPERATIONS:
            route = "/search-page-1.html" if operation == "search" else "/article-xml.xml"
            assert evaluate(client, path, 1, operation, route)
        assert not evaluate(client, path, 1, "fetch_html", "/article-a.html")


@pytest.mark.parametrize("role", ["admin", "operator", "reviewer", "viewer"])
def test_xml_proposal_and_approval_denied_to_non_stewards(scenario: Scenario, role: str) -> None:
    with scenario.client() as owner, scenario.client() as client:
        owner_auth = headers(scenario, owner, "owner")
        auth = headers(scenario, client, role)
        path = source_path(scenario)
        propose(owner, path, owner_auth)
        before = owner.get(path + "/policies").json()
        assert (
            client.post(
                path + "/policies",
                headers=auth,
                json={
                    "expected_version": 1,
                    "policy": xml_policy(),
                },
            ).status_code
            == 404
        )
        assert (
            client.post(path + "/policy-state", headers=auth, json=transition()).status_code == 404
        )
        assert owner.get(path + "/policies").json() == before


def test_xml_replacement_keeps_html_evidence_and_rejects_stale_state(scenario: Scenario) -> None:
    with scenario.client() as client:
        auth = headers(scenario, client, "owner")
        path = source_path(scenario)
        response = client.post(
            path + "/policies", headers=auth, json={"expected_version": 0, "policy": policy_body()}
        )
        assert response.status_code == 201, response.text
        response = client.post(path + "/policy-state", headers=auth, json=transition())
        assert response.status_code == 200, response.text
        original = response.json()
        assert evaluate(client, path, 1, "fetch_html", "/article-a.html")
        token = str(client.cookies[COOKIE])
        database = scenario.foundation.database
        query = text(
            "SELECT * FROM emailmonitor.source_policies "
            "WHERE organization_id=:org AND source_id='synthetic-publisher' AND version=1"
        )
        with database.tenant(token, scenario.organizations[0], Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            original_row = dict(
                c.execute(query, {"org": scenario.organizations[0]}).mappings().one()
            )
        propose(client, path, auth, version=1)
        history = client.get(path + "/policies").json()
        assert history[0]["version"] == 2 and history[0]["state"] == "pending_review"
        assert history[1] == original
        assert not evaluate(client, path, 1, "search", "/search-page-1.html")
        assert not evaluate(client, path, 2, "fetch_xml", "/article-xml.xml")
        assert (
            client.post(
                path + "/policies",
                headers=auth,
                json={
                    "expected_version": 1,
                    "policy": xml_policy(),
                },
            ).status_code
            == 409
        )
        for body in (transition(1, 2), transition(2, 2)):
            assert client.post(path + "/policy-state", headers=auth, json=body).status_code == 409
        assert client.get(path + "/policies").json() == history
        response = client.post(path + "/policy-state", headers=auth, json=transition(2))
        assert response.status_code == 200, response.text
        assert response.json()["allowed_operations"] == XML_OPERATIONS
        assert evaluate(client, path, 2, "fetch_xml", "/article-xml.xml")
        assert not evaluate(client, path, 2, "fetch_html", "/article-a.html")
        assert (
            client.post(
                path + "/policy-state", headers=auth, json=transition(2, 1, "suspended")
            ).status_code
            == 409
        )
        with database.tenant(token, scenario.organizations[0], Capability.READ_ORGANIZATION) as (
            c,
            _,
        ):
            assert (
                dict(c.execute(query, {"org": scenario.organizations[0]}).mappings().one())
                == original_row
            )
            assert (
                c.execute(
                    text(
                        "SELECT current_version FROM emailmonitor.source_policy_heads "
                        "WHERE source_id='synthetic-publisher'"
                    )
                ).scalar_one()
                == 2
            )


def test_xml_revoked_steward_cannot_propose_or_approve(scenario: Scenario) -> None:
    with scenario.client() as owner, scenario.client() as steward:
        owner_auth = headers(scenario, owner, "owner")
        steward_auth = headers(scenario, steward, "data_steward")
        path = source_path(scenario)
        propose(steward, path, steward_auth)
        before = owner.get(path + "/policies").json()
        org = scenario.organizations[0]
        identity = scenario.identities["data_steward"]
        response = owner.patch(
            f"/api/v1/organizations/{org}/members/{identity}",
            headers=owner_auth,
            json={
                "role": "data_steward",
                "status": "revoked",
                "expected_revision": 1,
            },
        )
        assert response.status_code == 200, response.text
        assert (
            steward.post(
                path + "/policies",
                headers=steward_auth,
                json={
                    "expected_version": 1,
                    "policy": xml_policy(),
                },
            ).status_code
            == 403
        )
        assert (
            steward.post(
                path + "/policy-state", headers=steward_auth, json=transition()
            ).status_code
            == 403
        )
        assert owner.get(path + "/policies").json() == before


def test_xml_tenant_b_cannot_mutate_tenant_a_pending_policy(scenario: Scenario) -> None:
    with scenario.client() as owner, scenario.client() as other:
        owner_auth = headers(scenario, owner, "owner")
        other_auth = headers(scenario, other, "owner_b")
        path = source_path(scenario)
        propose(owner, path, owner_auth)
        propose(other, source_path(scenario, 1), other_auth)
        before = owner.get(path + "/policies").json()
        assert (
            other.post(
                path + "/policies",
                headers=other_auth,
                json={
                    "expected_version": 1,
                    "policy": xml_policy(),
                },
            ).status_code
            == 404
        )
        assert (
            other.post(path + "/policy-state", headers=other_auth, json=transition()).status_code
            == 404
        )
        assert other.get(path + "/policies").status_code == 404
        token = str(other.cookies[COOKIE])
        with scenario.foundation.database.tenant(
            token,
            scenario.organizations[1],
            Capability.MANAGE_SOURCE_POLICY,
        ) as (c, _):
            assert c.execute(
                text("SELECT DISTINCT organization_id FROM emailmonitor.source_policies")
            ).scalars().all() == [scenario.organizations[1]]
            assert (
                c.execute(
                    text(
                        "UPDATE emailmonitor.source_policies SET state='approved' "
                        "WHERE organization_id=:org RETURNING version"
                    ),
                    {"org": scenario.organizations[0]},
                ).all()
                == []
            )
        assert owner.get(path + "/policies").json() == before
