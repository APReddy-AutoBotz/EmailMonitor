"""Trusted per-tenant service bindings for atomic human-initiated work.

Deployment supplies existing registered principals. This module cannot provision
logins or enroll historical work, and request bodies never select principals.
"""

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.runtime.authority import MAX_WORK_SECONDS, WorkPurpose

if TYPE_CHECKING:
    from sqlalchemy import Connection


class ServiceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    organization: UUID
    worker: UUID
    publisher: UUID
    seconds: int = Field(default=MAX_WORK_SECONDS, ge=1, le=MAX_WORK_SECONDS)

    @model_validator(mode="after")
    def distinct(self) -> "ServiceBinding":
        if self.worker == self.publisher or any(
            value.int == 0 for value in (self.organization, self.worker, self.publisher)
        ):
            raise ValueError("Separate explicit registered service principals required")
        return self


class ServiceBindings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: Literal["authored-html-service-reference", "controlled-xml-service-reference"] = (
        "authored-html-service-reference"
    )
    tenants: tuple[ServiceBinding, ...] = ()

    @model_validator(mode="after")
    def unique(self) -> "ServiceBindings":
        if len({entry.organization for entry in self.tenants}) != len(self.tenants):
            raise ValueError("Unique tenant bindings required")
        return self

    def issue(
        self, connection: "Connection", org: UUID, resource: UUID, purpose: WorkPurpose
    ) -> None:
        from sqlalchemy import text

        from emailmonitor.organizations.database import AuthorizationDenied

        binding = next((entry for entry in self.tenants if entry.organization == org), None)
        if binding is None:
            raise ValueError("Explicit service binding required for this tenant")
        if purpose == "extraction":
            start: str | None = connection.execute(
                text(
                    "SELECT plan->>'start_url' FROM emailmonitor.discovery "
                    "WHERE organization_id=:org AND job_id=:resource"
                ),
                {"org": org, "resource": resource},
            ).scalar_one_or_none()
            allowed = {
                "https://synthetic.publisher.example/" + name
                for name in (
                    "search-page-1.html",
                    "search-page-2.html",
                    "article-a.html",
                    "article-b.html",
                    "tooltip.html",
                    "no-contact.html",
                )
            }
            if self.profile == "controlled-xml-service-reference":
                from emailmonitor.extraction.pdf_fixture import DIGESTS
                from emailmonitor.sources.provider_documents import URLS

                # This composed profile owns the isolated PDF byte capability.
                # Only registered local fixtures join its route inventory; normal
                # start/delegation SQL still enforces job and source authority.
                allowed = (
                    allowed
                    | URLS
                    | {"https://synthetic.publisher.example/" + name for name in DIGESTS}
                )
            if start not in allowed:
                raise AuthorizationDenied()
        for principal in (binding.worker, binding.publisher):
            connection.execute(
                text(
                    "SELECT emailmonitor.delegate_service_work("
                    ":org,:principal,:resource,:purpose,:seconds)"
                ),
                {
                    "org": org,
                    "principal": principal,
                    "resource": resource,
                    "purpose": purpose,
                    "seconds": binding.seconds,
                },
            )
