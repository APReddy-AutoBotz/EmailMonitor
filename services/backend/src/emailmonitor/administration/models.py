"""Bounded tenant settings never confer source, role or network authorization."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Entitlements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    max_running_jobs: int = Field(default=2, ge=0, le=2)
    max_parallel_parse: int = Field(default=2, ge=0, le=2)
    max_parallel_export: int = Field(default=1, ge=0, le=1)
    max_parallel_browser: int = Field(default=1, ge=0, le=1)
    max_articles_per_job: int = Field(default=500, ge=0, le=500)
    monthly_resolution_units: int = Field(default=5000, ge=0, le=5000)
    max_export_bytes: int = Field(default=8388608, ge=0, le=8388608)
    browser_enabled: bool = True
    exports_enabled: bool = True


class Branding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    accent_color: str = Field(
        default="#155e63", min_length=7, max_length=7, pattern=r"^#[0-9a-f]{6}$"
    )
    label: str | None = Field(default=None, min_length=1, max_length=80)
    logo_reference: None = None

    @field_validator("label")
    @classmethod
    def printable_label(cls, value: str | None) -> str | None:
        import unicodedata

        if value is not None and (
            not value.strip()
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value)
        ):
            raise ValueError("Bounded printable presentation label required")
        return value


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    organization_id: UUID
    revision: int = Field(ge=1)
    entitlements: Entitlements
    branding: Branding
    support_reference: UUID
    deployment_mode: Literal["synthetic_offline"] = "synthetic_offline"
    billing_implemented: Literal[False] = False
    exceptional_support_grants_available: Literal[False] = False

    @field_validator("billing_implemented", "exceptional_support_grants_available", mode="before")
    @classmethod
    def actual_disabled_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Actual disabled capability boolean required")
        return value


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    entitlements: Entitlements
    branding: Branding


def effective_article_cap(entitlements: Entitlements, source_cap: int, requested: int) -> int:
    """A numerical intersection only, never permission to acquire or retain data."""
    if type(source_cap) is not int or type(requested) is not int:
        raise ValueError("Actual integer bounds required")
    if not 1 <= source_cap <= 500 or not 1 <= requested <= 500:
        raise ValueError("Bounded source and request required")
    return min(500, entitlements.max_articles_per_job, source_cap, requested)


class ResourceUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    organization_id: UUID
    period_start: date
    settled_resolution_units: int = Field(ge=0)
    reserved_resolution_units: int = Field(ge=0)
    monthly_unit_limit: int = Field(ge=0, le=5000)
    waiting_units: dict[
        Literal["fixture_io", "parse", "export", "browser", "http"],
        Annotated[int, Field(ge=0, le=10000)],
    ]
    active_units: dict[
        Literal["fixture_io", "parse", "export", "browser", "http"],
        Annotated[int, Field(ge=0, le=10000)],
    ]
    source_resource_attempts: int = Field(ge=0)
    billing_implemented: Literal[False] = False
    synthetic_only: Literal[True] = True

    @field_validator("billing_implemented", "synthetic_only", mode="before")
    @classmethod
    def actual_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Actual availability boolean required")
        return value
