"""Original extraction request and bounded durable state transitions."""

import hashlib
import json
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def no_explicit_null(cls, value: object) -> object:
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("Optional request fields must be omitted rather than null")
        return value


class KeywordInput(StrictModel):
    type: Literal["keyword"]
    source_id: str = Field(min_length=1, max_length=100)
    original_query: str = Field(min_length=1, max_length=2000)
    effective_query: str | None = Field(default=None, min_length=1, max_length=2000)
    query_change_confirmed: bool = False

    @model_validator(mode="after")
    def confirmed_change(self) -> "KeywordInput":
        if (
            self.effective_query not in (None, self.original_query)
            and not self.query_change_confirmed
        ):
            raise ValueError("Changed query requires explicit confirmation")
        return self


class URLInput(StrictModel):
    type: Literal["url"]
    url: str = Field(pattern=r"^https?://", max_length=8192)
    source_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("url")
    @classmethod
    def valid_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("HTTP URL syntax required; this does not authorize fetching")
        return value


class Filters(StrictModel):
    publication_from: date | None = None
    publication_to: date | None = None
    journal: str | None = Field(default=None, max_length=300)
    article_types: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )

    @field_validator("publication_from", "publication_to", mode="before")
    @classmethod
    def date_string(cls, value: object) -> object:
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError("ISO calendar date required")
            return parsed
        return value

    @model_validator(mode="after")
    def ordered(self) -> "Filters":
        if len(set(self.article_types)) != len(self.article_types):
            raise ValueError("Article types must be unique")
        if self.publication_from and self.publication_to:
            if self.publication_from > self.publication_to:
                raise ValueError("Publication interval must be ordered")
        return self


class Options(StrictModel):
    max_articles: int = Field(ge=1, le=10000)
    max_search_pages: int = Field(ge=1, le=1000)
    author_target: Literal["corresponding", "first", "both", "all"]
    max_link_depth: int = Field(default=2, ge=0, le=5)
    allow_pdf: bool = True
    allow_browser: bool = True
    allow_ocr: Literal[False] = False
    allow_wider_web: Literal[False] = False

    @field_validator("allow_ocr", "allow_wider_web", mode="before")
    @classmethod
    def false_boolean(cls, value: object) -> object:
        if type(value) is not bool or value is not False:
            raise ValueError("Unavailable option requires boolean false")
        return value


class JobRequest(StrictModel):
    schema_version: Literal["1.0"]
    input: Annotated[KeywordInput | URLInput, Field(discriminator="type")]
    purpose: str = Field(min_length=1, max_length=200)
    options: Options
    filters: Filters = Field(default_factory=Filters)


TERMINAL = frozenset({"cancelled", "completed", "completed_partial", "failed"})
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"awaiting_approval", "cancelled"}),
    "awaiting_approval": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"running", "pausing", "cancelling"}),
    "running": frozenset({"pausing", "cancelling", "completed", "completed_partial", "failed"}),
    "pausing": frozenset({"paused", "cancelling"}),
    "paused": frozenset({"queued", "cancelling"}),
    "cancelling": frozenset({"cancelled"}),
    **{state: frozenset() for state in TERMINAL},
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def effect_key(organization: str, job: str, item: str, input_digest: str) -> str:
    """Attempt-independent, tenant-bound fixture persistence effect identity."""
    return hashlib.sha256(
        canonical([organization, job, item, "persist", input_digest, "fixture-probe-v1"]).encode()
    ).hexdigest()
