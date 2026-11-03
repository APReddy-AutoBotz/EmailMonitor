"""Opaque, dispatch-scoped credential port. No secret-store backend is registered.

Only trusted gateway composition receives this port. References are not authority;
current tenant/source/lease state is checked independently. Secrets never enter the
provider request, response, parser, RPC or log contracts.
"""

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol

from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.fetching.sciencedirect import CredentialReference


@dataclass(frozen=True, repr=False)
class CredentialLease:
    reference: CredentialReference
    request_fingerprint: str
    api_key: bytes = field(repr=False)

    def header(self, reference: CredentialReference, fingerprint: str) -> bytes:
        if (
            type(self.reference) is not CredentialReference
            or CredentialReference.model_validate(self.reference.model_dump()) != reference
            or self.request_fingerprint != fingerprint
            or type(self.api_key) is not bytes
            or re.fullmatch(rb"[A-Za-z0-9_-]{1,256}", self.api_key) is None
        ):
            raise FetchDenied("provider_credential_scope_denied")
        return b"X-ELS-APIKey: " + self.api_key + b"\r\n"


class CredentialResolver(Protocol):
    """Backend must re-resolve exact tenant/source/origin/revision; no ambient key.

    Implementations own release of the short-lived handle on every exit. Python
    immutable bytes cannot promise memory zeroization. No concrete real resolver,
    storage URI, environment lookup or credential saving exists in this slice.
    """

    def open(
        self, reference: CredentialReference, request_fingerprint: str
    ) -> AbstractContextManager[CredentialLease]: ...


class UnavailableCredentials:
    def open(
        self, reference: CredentialReference, request_fingerprint: str
    ) -> AbstractContextManager[CredentialLease]:
        raise IsolationUnavailable("sciencedirect_credential_resolution_unimplemented")
