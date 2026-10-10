"""Real PostgreSQL integration. Missing DB is an explicit skip, never a pass."""

import base64
import hashlib
import os
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import jwt
import pytest
from api_client import APIClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from emailmonitor.api import create_app
from emailmonitor.config import Settings
from emailmonitor.identity.foundation import COOKIE, Foundation
from emailmonitor.identity.oidc import AuthenticationDenied, OIDCProvider
from emailmonitor.organizations.database import (
    AuthenticationDatabase,
    AuthorizationDenied,
    Database,
    digest,
)
from emailmonitor.organizations.roles import Capability
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

ISSUER = "https://identity.example.test"
ORIGIN = "https://app.example.test"
REDIRECT = ORIGIN + "/api/v1/auth/callback"


@dataclass
class FixtureExchange:
    codes: dict[str, tuple[str, str]] = field(default_factory=dict)

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        encoded, challenge = self.codes.pop(code)
        actual = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        if redirect_uri != REDIRECT or challenge != actual:
            raise AuthenticationDenied()
        return encoded


@dataclass
class Scenario:
    foundation: Foundation
    private_key: str
    exchange: FixtureExchange
    organizations: tuple[UUID, UUID]
    identities: dict[str, UUID]
    admin_url: str

    def client(self) -> APIClient:
        return APIClient(
            create_app(Settings(environment="test", identity_stub=True), self.foundation),
            base_url=ORIGIN,
        )

    def login(self, client: APIClient, role: str, **overrides: object) -> str:
        response = client.get("/api/v1/auth/start", follow_redirects=False)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        state = query["state"][0]
        claims: dict[str, object] = {
            "iss": ISSUER,
            "aud": "emailmonitor-test",
            "sub": str(self.identities[role]),
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "nonce": query["nonce"][0],
        }
        claims.update(overrides)
        encoded = jwt.encode(
            claims, self.private_key, algorithm="RS256", headers={"kid": "fixture"}
        )
        code = secrets.token_urlsafe(24)
        self.exchange.codes[code] = (encoded, query["code_challenge"][0])
        response = client.get("/api/v1/auth/callback", params={"state": state, "code": code})
        assert response.status_code == 200, response.text
        assert (
            "Secure" in response.headers["set-cookie"]
            and "HttpOnly" in response.headers["set-cookie"]
        )
        return str(response.json()["csrf_token"])


@pytest.fixture
def scenario() -> Iterator[Scenario]:
    admin_url = os.environ.get("EM_TEST_ADMIN_DATABASE_URL")
    runtime_url = os.environ.get("EM_TEST_DATABASE_URL")
    authentication_url = os.environ.get("EM_TEST_AUTH_DATABASE_URL")
    if not admin_url or not runtime_url or not authentication_url:
        pytest.skip("Real disposable PostgreSQL URLs are required for EM-002 SQL/API acceptance")
    admin = create_engine(admin_url)
    organizations = (uuid4(), uuid4())
    identities = {
        role: uuid4()
        for role in ("owner", "admin", "operator", "reviewer", "viewer", "data_steward", "owner_b")
    }
    with admin.begin() as connection:
        for identity in identities.values():
            connection.execute(
                text(
                    """
INSERT INTO emailmonitor.identities(id,issuer,subject)
VALUES(:id,:issuer,:sub)
"""
                ),
                {"id": identity, "issuer": ISSUER, "sub": str(identity)},
            )
        for index, organization in enumerate(organizations):
            connection.execute(
                text(
                    """
INSERT INTO emailmonitor.organizations(id,display_name,status,region)
VALUES(:id,:name,'active','test-only')
"""
                ),
                {"id": organization, "name": f"Synthetic tenant {index}"},
            )
        for label, identity in identities.items():
            organization = organizations[1] if label == "owner_b" else organizations[0]
            connection.execute(
                text(
                    "INSERT INTO emailmonitor.memberships VALUES(:org,:identity,:role,'active',1)"
                ),
                {
                    "org": organization,
                    "identity": identity,
                    "role": "owner" if label == "owner_b" else label,
                },
            )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    exchange = FixtureExchange()
    database = Database(runtime_url)
    authentication = AuthenticationDatabase(authentication_url)
    provider = OIDCProvider(
        ISSUER, "emailmonitor-test", ISSUER + "/authorize", REDIRECT, {"fixture": public}, exchange
    )
    test = Scenario(
        Foundation(database, provider, authentication),
        private,
        exchange,
        organizations,
        identities,
        admin_url,
    )
    yield test
    database.engine.dispose()
    authentication.engine.dispose()
    admin.dispose()


def test_real_api_tenant_selection_and_pool_reuse(scenario: Scenario) -> None:
    org_a, org_b = scenario.organizations
    with scenario.client() as client:
        scenario.login(client, "operator")
        session_a = str(client.cookies[COOKIE])
        assert client.get(f"/api/v1/organizations/{org_a}").status_code == 200
        assert (
            client.get(
                f"/api/v1/organizations/{org_b}", headers={"X-Organization-ID": str(org_b)}
            ).status_code
            == 404
        )
        assert len(client.get("/api/v1/me").json()["memberships"]) == 1
    with scenario.client() as client:
        scenario.login(client, "owner_b")
        session_b = str(client.cookies[COOKIE])
        assert client.get(f"/api/v1/organizations/{org_b}").status_code == 200
        assert client.get(f"/api/v1/organizations/{org_a}").status_code == 404
    db = scenario.foundation.database
    for token, org in ((session_a, org_a), (session_b, org_b), (session_a, org_a)):
        with db.tenant(token, org, Capability.READ_ORGANIZATION) as (connection, _):
            assert connection.execute(
                text("SELECT id FROM emailmonitor.organizations")
            ).scalars().all() == [org]
            assert connection.execute(
                text("SELECT DISTINCT organization_id FROM emailmonitor.memberships")
            ).scalars().all() == [org]
    with db.transaction() as connection:
        assert connection.execute(text("SELECT id FROM emailmonitor.organizations")).all() == []
        assert connection.execute(
            text("SELECT current_setting('emailmonitor.organization_id',true)")
        ).scalar() in ("", None)


def test_sql_rls_blocks_forged_tenant_and_contextless_writes(scenario: Scenario) -> None:
    org_a, org_b = scenario.organizations
    with scenario.client() as client:
        scenario.login(client, "owner")
        token = str(client.cookies[COOKIE])
    db = scenario.foundation.database
    with db.tenant(token, org_a, Capability.READ_ORGANIZATION) as (connection, _):
        connection.execute(
            text("SELECT set_config('emailmonitor.organization_id',:org,true)"), {"org": str(org_b)}
        )
        assert connection.execute(text("SELECT id FROM emailmonitor.organizations")).all() == []
        assert (
            connection.execute(
                text(
                    """
UPDATE emailmonitor.organizations SET display_name='forged' WHERE id=:org
RETURNING id
"""
                ),
                {"org": org_b},
            ).all()
            == []
        )
    with db.transaction() as connection:
        assert (
            connection.execute(text("SELECT organization_id FROM emailmonitor.memberships")).all()
            == []
        )
        assert (
            connection.execute(
                text("UPDATE emailmonitor.memberships SET status='revoked' RETURNING identity_id")
            ).all()
            == []
        )
        assert not connection.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).scalar()
    with pytest.raises(AuthorizationDenied), db.tenant(token, org_b, Capability.READ_ORGANIZATION):
        pass


@pytest.mark.parametrize("role", ["operator", "reviewer", "viewer", "data_steward"])
def test_roles_cannot_manage_members(scenario: Scenario, role: str) -> None:
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, role)
        assert client.get(f"/api/v1/organizations/{org}/members").status_code == 404
        response = client.patch(
            f"/api/v1/organizations/{org}/members/{scenario.identities['viewer']}",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"role": "admin", "status": "active", "expected_revision": 1},
        )
        assert response.status_code == 404


def test_owner_transfer_guard_and_atomic_transfer(scenario: Scenario) -> None:
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        response = client.patch(
            f"/api/v1/organizations/{org}/members/{scenario.identities['owner']}",
            headers=headers,
            json={"role": "admin", "status": "active", "expected_revision": 1},
        )
        assert response.status_code == 409
        response = client.post(
            f"/api/v1/organizations/{org}/owner-transfer",
            headers=headers,
            json={"target_identity_id": str(scenario.identities["admin"]), "expected_revision": 1},
        )
        assert response.status_code == 200, response.text
        assert client.get("/api/v1/me").status_code == 401
    with scenario.client() as client:
        scenario.login(client, "admin")
        members = client.get(f"/api/v1/organizations/{org}/members").json()
        assert (
            next(row for row in members if row["identity_id"] == str(scenario.identities["admin"]))[
                "role"
            ]
            == "owner"
        )


def test_admin_cannot_assign_or_change_owner(scenario: Scenario) -> None:
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, "admin")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        for identity, role in (
            (scenario.identities["owner"], "viewer"),
            (scenario.identities["viewer"], "owner"),
        ):
            response = client.patch(
                f"/api/v1/organizations/{org}/members/{identity}",
                headers=headers,
                json={"role": role, "status": "active", "expected_revision": 1},
            )
            assert response.status_code == 404


def test_revocation_stale_session_csrf_and_revision(scenario: Scenario) -> None:
    org = scenario.organizations[0]
    with scenario.client() as viewer, scenario.client() as owner:
        viewer_csrf = scenario.login(viewer, "viewer")
        owner_csrf = scenario.login(owner, "owner")
        route = f"/api/v1/organizations/{org}/members/{scenario.identities['viewer']}"
        body = {"role": "viewer", "status": "revoked", "expected_revision": 1}
        assert owner.patch(route, json=body).status_code == 403
        assert (
            owner.patch(
                route,
                headers={"Origin": "https://evil.example", "X-CSRF-Token": owner_csrf},
                json=body,
            ).status_code
            == 403
        )
        assert (
            owner.patch(
                route, headers={"Origin": ORIGIN, "X-CSRF-Token": viewer_csrf}, json=body
            ).status_code
            == 403
        )
        headers = {"Origin": ORIGIN, "X-CSRF-Token": owner_csrf}
        assert (
            owner.patch(route, headers=headers, json={**body, "expected_revision": 2}).status_code
            == 409
        )
        assert owner.patch(route, headers=headers, json=body).status_code == 200
        assert viewer.get("/api/v1/me").status_code == 401
        assert viewer.get(f"/api/v1/organizations/{org}").status_code == 404


def test_lifecycle_suspension_recovery_and_terminal_state(scenario: Scenario) -> None:
    org = scenario.organizations[0]
    with scenario.client() as owner, scenario.client() as viewer:
        csrf = scenario.login(owner, "owner")
        scenario.login(viewer, "viewer")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        route = f"/api/v1/organizations/{org}/lifecycle"
        assert (
            owner.post(
                route, headers=headers, json={"status": "suspended", "expected_revision": 1}
            ).status_code
            == 200
        )
        assert viewer.get(f"/api/v1/organizations/{org}").status_code == 404
        assert (
            owner.post(
                route, headers=headers, json={"status": "deleted", "expected_revision": 2}
            ).status_code
            == 409
        )
        assert (
            owner.post(
                route, headers=headers, json={"status": "active", "expected_revision": 2}
            ).status_code
            == 200
        )
        assert (
            owner.post(
                route, headers=headers, json={"status": "offboarding", "expected_revision": 3}
            ).status_code
            == 200
        )
        assert (
            owner.post(
                route, headers=headers, json={"status": "deleted", "expected_revision": 4}
            ).status_code
            == 200
        )
        assert (
            owner.post(
                route, headers=headers, json={"status": "active", "expected_revision": 5}
            ).status_code
            == 404
        )


def test_expired_revoked_and_fabricated_session(scenario: Scenario) -> None:
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        assert (
            client.post(
                "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
            ).status_code
            == 204
        )
        assert client.get("/api/v1/me").status_code == 401
        scenario.login(client, "owner")
        token = str(client.cookies[COOKIE])
        admin = create_engine(scenario.admin_url)
        with admin.begin() as connection:
            connection.execute(
                text(
                    """
UPDATE emailmonitor.sessions SET expires_at=now()-interval '1 second' WHERE
token_hash=:token
"""
                ),
                {"token": digest(token)},
            )
        admin.dispose()
        assert client.get("/api/v1/me").status_code == 401
        client.cookies.set(COOKIE, "fabricated", domain="app.example.test", path="/")
        assert client.get("/api/v1/me").status_code == 401


def test_runtime_rejects_owner_connection(scenario: Scenario) -> None:
    with pytest.raises(ValueError):
        Database(scenario.admin_url)


def test_force_rls_and_composite_keys(scenario: Scenario) -> None:
    with scenario.foundation.database.transaction() as connection:
        rows = connection.execute(
            text(
                """
SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE
relnamespace='emailmonitor'::regnamespace AND relname IN
('organizations','memberships','audit_events')
"""
            )
        ).all()
        assert len(rows) == 3 and all(
            row.relrowsecurity and row.relforcerowsecurity for row in rows
        )
        with pytest.raises(SQLAlchemyError), connection.begin_nested():
            connection.execute(text("SELECT token_hash FROM emailmonitor.sessions"))


def test_oidc_browser_binding_and_callback_replay(scenario: Scenario) -> None:
    with scenario.client() as client, scenario.client() as stranger:
        response = client.get("/api/v1/auth/start", follow_redirects=False)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        state = query["state"][0]
        assert query["code_challenge_method"] == ["S256"]
        assert "code_verifier" not in query
        claims = {
            "iss": ISSUER,
            "aud": "emailmonitor-test",
            "sub": str(scenario.identities["owner"]),
            "nonce": query["nonce"][0],
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }
        encoded = jwt.encode(
            claims, scenario.private_key, algorithm="RS256", headers={"kid": "fixture"}
        )
        scenario.exchange.codes["synthetic-once"] = (encoded, query["code_challenge"][0])
        assert (
            stranger.get(
                "/api/v1/auth/callback", params={"state": state, "code": "synthetic-once"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/auth/callback", params={"state": "wrong", "code": "synthetic-once"}
            ).status_code
            == 401
        )
        response = client.get(
            "/api/v1/auth/callback", params={"state": state, "code": "synthetic-once"}
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert (
            client.get(
                "/api/v1/auth/callback", params={"state": state, "code": "synthetic-once"}
            ).status_code
            == 401
        )
        assert client.get("/api/v1/me").headers["cache-control"] == "no-store"


def test_test_provider_cannot_activate_in_production(scenario: Scenario) -> None:
    with pytest.raises(ValueError):
        create_app(Settings(), scenario.foundation)
    with pytest.raises(ValueError):
        create_app(Settings(environment="test"), scenario.foundation)


def test_registered_membership_addition_is_tenant_scoped(scenario: Scenario) -> None:
    org_a, org_b = scenario.organizations
    with scenario.client() as owner:
        csrf = scenario.login(owner, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        response = owner.post(
            f"/api/v1/organizations/{org_a}/members",
            headers=headers,
            json={"identity_id": str(scenario.identities["owner_b"]), "role": "viewer"},
        )
        assert response.status_code == 201
        assert (
            owner.post(
                f"/api/v1/organizations/{org_b}/members",
                headers=headers,
                json={"identity_id": str(scenario.identities["viewer"]), "role": "operator"},
            ).status_code
            == 404
        )
        assert (
            owner.post(
                f"/api/v1/organizations/{org_a}/members",
                headers=headers,
                json={"identity_id": str(uuid4()), "role": "operator"},
            ).status_code
            == 404
        )
    with scenario.client() as member:
        scenario.login(member, "owner_b")
        memberships = member.get("/api/v1/me").json()["memberships"]
        assert len(memberships) == 2
        assert member.get(f"/api/v1/organizations/{org_a}").status_code == 200
        assert member.get(f"/api/v1/organizations/{org_a}/members").status_code == 404


def test_concurrent_last_owner_removal_is_serialized(scenario: Scenario) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    org = scenario.organizations[0]
    with scenario.client() as first:
        csrf = scenario.login(first, "owner")
        assert (
            first.patch(
                f"/api/v1/organizations/{org}/members/{scenario.identities['admin']}",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"role": "owner", "status": "active", "expected_revision": 1},
            ).status_code
            == 200
        )

    def remove(role: str, revision: int) -> int:
        db = Database(scenario.foundation.database.engine.url.render_as_string(hide_password=False))
        isolated = Foundation(db, scenario.foundation.provider, scenario.foundation.authentication)
        try:
            with APIClient(
                create_app(Settings(environment="test", identity_stub=True), isolated), ORIGIN
            ) as client:
                csrf = scenario.login(client, role)
                barrier.wait(timeout=10)
                return client.patch(
                    f"/api/v1/organizations/{org}/members/{scenario.identities[role]}",
                    headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                    json={"role": "admin", "status": "active", "expected_revision": revision},
                ).status_code
        finally:
            db.engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: remove(*item), [("owner", 1), ("admin", 2)]))
    assert sorted(results) == [200, 409]


def test_database_runtime_is_direct_login_and_revision_body_is_strict(scenario: Scenario) -> None:
    with scenario.foundation.database.transaction() as connection:
        assert connection.execute(text("SELECT current_user=session_user")).scalar_one()
        assert str(connection.execute(text("SHOW server_version")).scalar_one()).startswith("17.11")
        with pytest.raises(SQLAlchemyError), connection.begin_nested():
            connection.execute(text("SELECT issuer,subject FROM emailmonitor.identities"))
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        response = client.patch(
            f"/api/v1/organizations/{org}/members/{scenario.identities['viewer']}",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={
                "role": "viewer",
                "status": "active",
                "expected_revision": 1,
                "organization_id": str(scenario.organizations[1]),
            },
        )
        assert response.status_code == 422


def test_authentication_and_runtime_privileges_are_separate(scenario: Scenario) -> None:
    functions = (
        "emailmonitor.establish_session(text,text,text,text)",
        "emailmonitor.put_login_flow(text,text,text)",
        "emailmonitor.consume_login_flow(text)",
    )
    for pool, authentication in (
        (scenario.foundation.database, False),
        (scenario.foundation.authentication, True),
    ):
        with pool.transaction() as connection:
            for function in functions:
                assert (
                    connection.execute(
                        text("SELECT has_function_privilege(current_user,:function,'EXECUTE')"),
                        {"function": function},
                    ).scalar_one()
                    is authentication
                )
            forbidden = "emailmonitor_runtime" if authentication else "emailmonitor_authenticator"
            for privilege in ("MEMBER", "SET"):
                assert (
                    connection.execute(
                        text("SELECT pg_has_role(current_user,:role,:privilege)"),
                        {"role": forbidden, "privilege": privilege},
                    ).scalar_one()
                    is False
                )
            if authentication:
                for table in (
                    "organizations",
                    "memberships",
                    "audit_events",
                    "identities",
                    "sessions",
                ):
                    assert (
                        connection.execute(
                            text("SELECT has_table_privilege(current_user,:table,'SELECT')"),
                            {"table": "emailmonitor." + table},
                        ).scalar_one()
                        is False
                    )
    with pytest.raises(ValueError, match="isolated"):
        Database(
            scenario.foundation.authentication.engine.url.render_as_string(hide_password=False)
        )
    with pytest.raises(ValueError, match="isolated"):
        AuthenticationDatabase(
            scenario.foundation.database.engine.url.render_as_string(hide_password=False)
        )
    with scenario.client() as client:
        scenario.login(client, "owner")
        assert client.get(f"/api/v1/organizations/{scenario.organizations[0]}").status_code == 200
