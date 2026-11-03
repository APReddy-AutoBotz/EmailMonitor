import time
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from emailmonitor.identity.oidc import AuthenticationDenied, OIDCProvider


@dataclass
class Exchange:
    token: str

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        assert code == "synthetic-code" and verifier == "synthetic-verifier"
        assert redirect_uri == "https://app.example.test/callback"
        return self.token


@pytest.fixture
def keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )


def provider(public: str, encoded: str) -> OIDCProvider:
    return OIDCProvider(
        "https://identity.example.test",
        "test-client",
        "https://identity.example.test/authorize",
        "https://app.example.test/callback",
        {"synthetic": public},
        Exchange(encoded),
    )


def claims() -> dict[str, object]:
    return {
        "iss": "https://identity.example.test",
        "aud": "test-client",
        "sub": "synthetic-subject",
        "nonce": "expected-nonce",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://evil.example"},
        {"aud": "another-client"},
        {"nonce": "wrong"},
        {"exp": 1},
        {"iat": int(time.time()) + 86400},
        {"sub": ""},
        {"azp": "another-client"},
        {"aud": ["test-client", "another-client"]},
    ],
)
def test_id_token_rejects_wrong_registered_claims(
    keypair: tuple[str, str], change: dict[str, object]
) -> None:
    private, public = keypair
    token = jwt.encode(
        {**claims(), **change}, private, algorithm="RS256", headers={"kid": "synthetic"}
    )
    with pytest.raises(AuthenticationDenied):
        provider(public, token).verify_code(
            "synthetic-code", "synthetic-verifier", "expected-nonce"
        )


@pytest.mark.parametrize("missing", ["iss", "aud", "sub", "nonce", "exp", "iat"])
def test_id_token_requires_registered_claims(keypair: tuple[str, str], missing: str) -> None:
    private, public = keypair
    values = claims()
    del values[missing]
    token = jwt.encode(values, private, algorithm="RS256", headers={"kid": "synthetic"})
    with pytest.raises(AuthenticationDenied):
        provider(public, token).verify_code(
            "synthetic-code", "synthetic-verifier", "expected-nonce"
        )


def test_token_algorithm_key_selection_and_claimed_roles_are_not_authority(
    keypair: tuple[str, str],
) -> None:
    private, public = keypair
    signed = jwt.encode(
        {**claims(), "role": "owner", "organization_id": "forged"},
        private,
        algorithm="RS256",
        headers={"kid": "synthetic"},
    )
    assert provider(public, signed).verify_code(
        "synthetic-code", "synthetic-verifier", "expected-nonce"
    ) == ("https://identity.example.test", "synthetic-subject")
    for encoded in (
        jwt.encode(
            claims(),
            "a-long-synthetic-secret-only-for-testing",
            algorithm="HS256",
            headers={"kid": "synthetic"},
        ),
        jwt.encode(claims(), private, algorithm="RS256", headers={"kid": "untrusted"}),
        jwt.encode(claims(), "", algorithm="none", headers={"kid": "synthetic"}),
        "malformed",
    ):
        with pytest.raises(AuthenticationDenied):
            provider(public, encoded).verify_code(
                "synthetic-code", "synthetic-verifier", "expected-nonce"
            )
