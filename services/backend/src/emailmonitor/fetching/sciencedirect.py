"""Provider request/response boundary, with no socket, resolver or secret access.

These reusable checks consume a response supplied by a trusted protected transport;
they do not establish its DNS/TLS/peer evidence. No such live transport is registered.
The default current-authority provider refuses all work. A binding is a comparison
value created by server composition, never a permission grant from a caller or page.
"""

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, NoReturn
from uuid import UUID

from pydantic import Field, model_validator

from emailmonitor.fetching.plan import HopPlanner, PlanScope
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable, SafeURL
from emailmonitor.sources.policy import Operation
from emailmonitor.sources.sciencedirect import (
    API_ORIGIN,
    ArticleIdentifier,
    Contract,
    RequestPlan,
    SearchPage,
    SearchRequest,
    article_path,
    parse_search,
)
from emailmonitor.sources.sciencedirect import (
    MAX_BYTES as SEARCH_MAX_BYTES,
)

SOURCE = "elsevier_sciencedirect_v2"
HOSTS = frozenset({"api.elsevier.com"})
XML_MAX_BYTES = 2_097_152


class ProviderRequest(Contract):
    """Only canonical typed requests; arbitrary RequestPlan values are not accepted."""

    search: SearchRequest | None = None
    article: ArticleIdentifier | None = None
    view: Literal["FULL"] | None = None

    @model_validator(mode="after")
    def one_route(self) -> "ProviderRequest":
        if (self.search is None) == (self.article is None):
            raise ValueError("Exactly one supported provider request required")
        if self.search is not None and self.view is not None:
            raise ValueError("Article view is not a search parameter")
        if self.article is not None:
            article_path(self.article)
        return self

    def plan(self) -> RequestPlan:
        if self.search is not None:
            return self.search.plan()
        assert self.article is not None
        return RequestPlan(
            method="GET",
            path=article_path(self.article) + ("?view=FULL" if self.view == "FULL" else ""),
            media_type="text/xml",
        )

    @property
    def url(self) -> str:
        return API_ORIGIN + self.plan().path

    @property
    def operation(self) -> Operation:
        return Operation.SEARCH if self.search is not None else Operation.XML

    @property
    def max_bytes(self) -> int:
        return SEARCH_MAX_BYTES if self.search is not None else XML_MAX_BYTES

    @property
    def fingerprint(self) -> str:
        plan = self.plan()
        canonical = json.dumps(
            [plan.method, self.url, plan.media_type, hashlib.sha256(plan.body).hexdigest()],
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(canonical).hexdigest()


class CredentialReference(Contract):
    """Opaque reference only, not a key, header, secret-manager URI or resolver."""

    organization: UUID
    reference: UUID
    revision: int = Field(ge=1)
    source: Literal["elsevier_sciencedirect_v2"] = "elsevier_sciencedirect_v2"
    origin: Literal["https://api.elsevier.com"] = API_ORIGIN


class ProviderBinding(Contract):
    organization: UUID
    job: UUID
    item: UUID
    lease: UUID = Field(repr=False)
    generation: int = Field(ge=1)
    deletion_generation: int = Field(ge=1)
    policy_version: int = Field(ge=1)
    policy_revision: int = Field(ge=1)
    discovery_revision: int = Field(ge=1)
    source: Literal["elsevier_sciencedirect_v2"] = "elsevier_sciencedirect_v2"
    purpose: Literal["academic_contact_research"] = "academic_contact_research"
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    credential: CredentialReference = Field(repr=False)
    deadline: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def tenant_reference(self) -> "ProviderBinding":
        if self.credential.organization != self.organization:
            raise ValueError("Credential reference must belong to the current tenant")
        return self


def _binding_matches(value: object, expected: ProviderBinding) -> bool:
    if type(value) is not ProviderBinding:
        return False
    try:
        # model_copy/model_construct bypass validation; True must not equal revision1.
        checked = ProviderBinding.model_validate(value.model_dump())
    except (ValueError, TypeError):
        return False
    return checked == expected


@dataclass(frozen=True)
class ProviderResponse:
    """Transport-owned response metadata, checked against the server-owned request.

    Binding is attached by the trusted dispatch context, never read from HTTP headers
    or publisher content. It distinguishes same-URL searches/tenants/leases. The
    transport must close its stream on every exit, reject ambiguous HTTP framing,
    enforce per-read deadlines, and obtain actual DNS/peer/TLS evidence. The iterable
    here is not a substitute for those I/O controls and may not follow redirects.
    """

    url: str
    status: int
    content_type: str
    chunks: Iterable[bytes] = field(repr=False)
    binding: ProviderBinding = field(repr=False)
    content_length: int | None = None
    content_encoding: str | None = None


@dataclass(frozen=True)
class AcquiredResponse:
    request: ProviderRequest
    binding: ProviderBinding = field(repr=False)
    body: bytes = field(repr=False)
    content_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.request) is not ProviderRequest
            or type(self.binding) is not ProviderBinding
            or not _binding_matches(self.binding, self.binding)
            or self.binding.request_fingerprint != self.request.fingerprint
            or type(self.body) is not bytes
            or not 1 <= len(self.body) <= self.request.max_bytes
            or self.content_digest != hashlib.sha256(self.body).hexdigest()
        ):
            raise FetchDenied("provider_response_binding_denied")


def inactive_authority() -> NoReturn:
    raise IsolationUnavailable("sciencedirect_live_admission_unimplemented")


class ProviderBoundary:
    """One immutable request with current authority checks and shared hop planning.

    Trusted future composition must resolve the current binding from database/source/
    entitlement/admission/lease state at each check. Never implement current() from
    submitted identifiers or a cached request. This class is not API/worker registered.
    """

    def __init__(
        self,
        request: ProviderRequest,
        binding: ProviderBinding,
        current: Callable[[], ProviderBinding] = inactive_authority,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # Revalidate immutable contracts, including deliberately bypassed model copies.
        self.request = ProviderRequest.model_validate(request.model_dump())
        self.binding = ProviderBinding.model_validate(binding.model_dump())
        if self.binding.request_fingerprint != self.request.fingerprint:
            raise FetchDenied("provider_request_binding_denied")
        self._current = current
        self.planner = HopPlanner(
            PlanScope(
                organization=binding.organization,
                source=SOURCE,
                policy_version=binding.policy_version,
                operation=request.operation,
                allowed_hosts=HOSTS,
                deadline=binding.deadline,
                max_redirects=0,
            ),
            self._authorize,
            clock,
        )
        self.check_current()

    def _authorize(self, scope: PlanScope, url: SafeURL) -> None:
        if (
            scope != self.planner.scope
            or url.normalized != self.request.url
            or not _binding_matches(self._current(), self.binding)
        ):
            raise FetchDenied("provider_current_binding_denied")

    def check_current(self) -> None:
        try:
            request = ProviderRequest.model_validate(self.request.model_dump())
            binding = ProviderBinding.model_validate(self.binding.model_dump())
            if (
                type(self.request) is not ProviderRequest
                or type(self.binding) is not ProviderBinding
                or request != self.request
                or binding != self.binding
                or binding.request_fingerprint != request.fingerprint
                or self.planner.scope
                != PlanScope(
                    binding.organization,
                    SOURCE,
                    binding.policy_version,
                    request.operation,
                    HOSTS,
                    binding.deadline,
                    0,
                )
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise FetchDenied("provider_request_binding_denied") from None
        self.planner.authorize_url(self.request.url)

    def read_response(self, response: ProviderResponse) -> AcquiredResponse:
        """Bound streaming and reauthorization; no request dispatch or retry exists."""
        self.check_current()
        if type(response) is not ProviderResponse or response.url != self.request.url:
            raise FetchDenied("provider_response_origin_denied")
        if not _binding_matches(response.binding, self.binding):
            raise FetchDenied("provider_response_binding_denied")
        if type(response.status) is not int or response.status != 200:
            # Includes every redirect, 401/403/429 and provider challenge.
            raise FetchDenied("source_response_denied")
        if (
            type(response.content_type) is not str
            or response.content_type.lower() not in self._media_types()
        ):
            raise FetchDenied("content_type_denied")
        if response.content_encoding not in (None, "identity"):
            raise FetchDenied("compressed_response_denied")
        if response.content_length is not None and (
            type(response.content_length) is not int
            or not 1 <= response.content_length <= self.request.max_bytes
        ):
            raise FetchDenied("body_limit_exceeded")
        body = bytearray()
        try:
            chunks = iter(response.chunks)
        except Exception:
            raise FetchDenied("provider_stream_denied") from None
        end = object()
        for _ in range(4097):
            self.check_current()
            try:
                chunk = next(chunks, end)
            except Exception:
                raise FetchDenied("provider_stream_denied") from None
            self.check_current()
            if chunk is end:
                break
            if type(chunk) is not bytes:
                raise FetchDenied("provider_chunk_denied")
            if len(body) + len(chunk) > self.request.max_bytes:
                raise FetchDenied("body_limit_exceeded")
            body.extend(chunk)
        else:
            raise FetchDenied("provider_chunk_limit_exceeded")
        if not body or (
            response.content_length is not None and response.content_length != len(body)
        ):
            raise FetchDenied("response_framing_denied")
        self.check_current()
        data = bytes(body)
        return AcquiredResponse(self.request, self.binding, data, hashlib.sha256(data).hexdigest())

    def _media_types(self) -> frozenset[str]:
        # Exact, small declared set; no HTML challenge, arbitrary charset or XML suffix.
        base = (
            ("application/json",)
            if self.request.search is not None
            else (
                "text/xml",
                "application/xml",
            )
        )
        return frozenset(value for media in base for value in (media, media + "; charset=utf-8"))

    def parse_search(self, response: AcquiredResponse) -> SearchPage:
        self.require_response(response)
        if self.request.search is None:
            raise FetchDenied("provider_route_denied")
        page = parse_search(response.body, self.request.search)
        self.check_current()
        return page

    def require_response(self, response: AcquiredResponse) -> None:
        self.check_current()
        if (
            type(response) is not AcquiredResponse
            or response.request != self.request
            or not _binding_matches(response.binding, self.binding)
            or response.content_digest != hashlib.sha256(response.body).hexdigest()
        ):
            raise FetchDenied("provider_response_binding_denied")


def acquire_live(boundary: ProviderBoundary) -> NoReturn:
    """No live transport, credential resolution or activation switch exists."""
    raise IsolationUnavailable("sciencedirect_protected_transport_unimplemented")
