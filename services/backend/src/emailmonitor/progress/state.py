"""Truthful durable outcome/counter semantics; no fetching or stream authority."""

from collections import Counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Outcome = Literal[
    "pending",
    "running",
    "retry_wait",
    "succeeded",
    "no_contact",
    "needs_review",
    "policy_blocked",
    "access_blocked",
    "unsupported",
    "skipped",
    "failed",
    "cancelled",
]
TERMINAL: frozenset[Outcome] = frozenset(
    {
        "succeeded",
        "no_contact",
        "needs_review",
        "policy_blocked",
        "access_blocked",
        "unsupported",
        "skipped",
        "failed",
        "cancelled",
    }
)
GAPS: frozenset[Outcome] = TERMINAL - {"succeeded", "no_contact", "needs_review"}


class ItemCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    discovered: int = Field(ge=0, le=500)
    pending: int = Field(ge=0, le=500)
    active: int = Field(ge=0, le=500)
    retry_wait: int = Field(ge=0, le=500)
    terminal: int = Field(ge=0, le=500)
    by_outcome: dict[Outcome, int]

    @model_validator(mode="after")
    def conserved(self) -> "ItemCounts":
        if any(value < 0 or value > 500 for value in self.by_outcome.values()):
            raise ValueError("Bounded outcome counts required")
        if sum(self.by_outcome.values()) != self.discovered:
            raise ValueError("Outcome counts must conserve discovered items")
        expected = (
            self.by_outcome.get("pending", 0),
            self.by_outcome.get("running", 0),
            self.by_outcome.get("retry_wait", 0),
            sum(value for outcome, value in self.by_outcome.items() if outcome in TERMINAL),
        )
        if expected != (self.pending, self.active, self.retry_wait, self.terminal):
            raise ValueError("Counters disagree with durable outcomes")
        return self


def counts(outcomes: list[Outcome]) -> ItemCounts:
    values = dict(Counter(outcomes))
    return ItemCounts(
        discovered=len(outcomes),
        pending=values.get("pending", 0),
        active=values.get("running", 0),
        retry_wait=values.get("retry_wait", 0),
        terminal=sum(n for key, n in values.items() if key in TERMINAL),
        by_outcome=values,
    )


def completion(
    counters: ItemCounts, *, enumeration_stopped: bool, discovery_complete: bool
) -> Literal["completed", "completed_partial"] | None:
    """No-contact and review quality never imply an execution gap."""
    if not enumeration_stopped or counters.pending or counters.active or counters.retry_wait:
        return None
    if not discovery_complete or any(counters.by_outcome.get(key, 0) for key in GAPS):
        return "completed_partial"
    return "completed"


def percentage(counters: ItemCounts, discovery_complete: bool) -> int | None:
    # Source-reported entries may include duplicates and are never the denominator.
    if not discovery_complete:
        return None
    return 100 if counters.discovered == 0 else counters.terminal * 100 // counters.discovered


def parse_cursor(organization: UUID, job: UUID, value: str | None) -> int:
    if value is None or value == "":
        return 0
    if not isinstance(value, str) or len(value) > 94 or value.count(":") != 1:
        raise ValueError("Bounded tenant-job replay cursor required")
    identifier, ordinal = value.split(":")
    if identifier != f"{organization}/{job}" or not ordinal.isascii() or not ordinal.isdecimal():
        raise ValueError("Cursor is not bound to the requested job")
    number = int(ordinal)
    if str(number) != ordinal or not 0 <= number <= 9223372036854775807:
        raise ValueError("Canonical bounded replay ordinal required")
    return number


def cursor(organization: UUID, job: UUID, sequence: int) -> str:
    value = f"{organization}/{job}:{sequence}"
    parse_cursor(organization, job, value)
    return value
