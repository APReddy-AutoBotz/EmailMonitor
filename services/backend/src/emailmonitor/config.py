"""Fail-closed scaffold configuration shared by application entry points."""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment: Literal["development", "test", "production"] = "production"
    fixture_mode: bool = False
    identity_stub: bool = False
    live_sources_enabled: bool = False
    outbound_email_enabled: bool = False
    external_ai_enabled: bool = False
    wider_web_enabled: bool = False
    ocr_enabled: bool = False

    @model_validator(mode="after")
    def validate_boundary(self) -> "Settings":
        if self.environment != "test" and (self.fixture_mode or self.identity_stub):
            raise ValueError("Fixture and identity-stub modes require the test environment")
        if any(
            (
                self.live_sources_enabled,
                self.outbound_email_enabled,
                self.external_ai_enabled,
                self.wider_web_enabled,
                self.ocr_enabled,
            )
        ):
            raise ValueError("Outbound capabilities are unavailable in EM-001")
        return self

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "Settings":
        values: dict[str, object] = {}
        fields = cls.model_fields
        for key, value in env.items():
            if not key.startswith("EMAILMONITOR_"):
                continue
            field = key.removeprefix("EMAILMONITOR_").lower()
            if field not in fields:
                raise ValueError("Unknown EmailMonitor configuration key")
            if field == "environment":
                values[field] = value
            elif value in ("true", "false"):
                values[field] = value == "true"
            else:
                raise ValueError("Boolean configuration must be true or false")
        return cls.model_validate(values)
