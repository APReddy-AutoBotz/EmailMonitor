"""Standards-based OIDC verification; exchange adapter has no default network path."""

import base64
import hashlib
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode, urlsplit

import jwt


class AuthenticationDenied(Exception):
    """Sanitized identity failure; never expose upstream claims or tokens."""


class TokenExchange(Protocol):
    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str: ...


@dataclass(frozen=True)
class OIDCProvider:
    issuer: str
    client_id: str
    authorization_endpoint: str
    redirect_uri: str
    verification_keys: dict[str, str]
    exchange_adapter: TokenExchange
    test_only: bool = True

    def __post_init__(self) -> None:
        for value in (self.issuer, self.authorization_endpoint, self.redirect_uri):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("OIDC endpoints must be exact reviewed HTTPS endpoints")
        if not self.client_id or not self.verification_keys:
            raise ValueError("Explicit OIDC audience and pinned verification keys required")

    @property
    def origin(self) -> str:
        parsed = urlsplit(self.redirect_uri)
        return f"{parsed.scheme}://{parsed.netloc}"

    def authorization_url(self, state: str, nonce: str, verifier: str) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(
            b"="
        )
        return (
            self.authorization_endpoint
            + "?"
            + urlencode(
                {
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "response_type": "code",
                    "scope": "openid",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge.decode(),
                    "code_challenge_method": "S256",
                }
            )
        )

    def verify_code(self, code: str, verifier: str, nonce: str) -> tuple[str, str]:
        try:
            encoded = self.exchange_adapter.exchange(code, verifier, self.redirect_uri)
            header = jwt.get_unverified_header(encoded)
            key = self.verification_keys[header["kid"]]
            claims = jwt.decode(
                encoded,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.client_id,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
            )
            if (
                not isinstance(claims["sub"], str)
                or not claims["sub"]
                or claims["nonce"] != nonce
                or claims.get("azp", self.client_id) != self.client_id
                or (
                    isinstance(claims["aud"], list)
                    and len(claims["aud"]) > 1
                    and claims.get("azp") != self.client_id
                )
            ):
                raise AuthenticationDenied()
            return self.issuer, claims["sub"]
        except (jwt.PyJWTError, KeyError, ValueError, TypeError) as error:
            raise AuthenticationDenied() from error
