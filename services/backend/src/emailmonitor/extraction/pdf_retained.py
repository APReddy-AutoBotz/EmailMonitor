"""Retained authored-PDF contract; constructing a record grants no execution authority.

The raw parser's evidence rules remain intact. Locator-only PDF retention is not
implemented: retaining observed facts requires existing excerpt permission.
"""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from emailmonitor.extraction.html import Fact
from emailmonitor.extraction.pdf import PdfObservation
from emailmonitor.extraction.pdf_fixture import DIGESTS

MAX_ENVELOPE = 131072


class PdfBinding(Fact):
    organization: UUID
    job: UUID
    item: UUID
    generation: int = Field(ge=1)
    deletion_generation: int = Field(ge=1)
    policy_version: int = Field(ge=1)
    discovery_revision: int = Field(ge=1)


class RetainedPdf(PdfObservation):
    retention_profile: Literal["authored-pdf-retention-v1"] = "authored-pdf-retention-v1"
    input_mode: Literal["authored_local_fixture"] = "authored_local_fixture"
    isolation_profile: Literal["network-none-parser-v1"] = "network-none-parser-v1"
    binding: PdfBinding
    excerpts_retained: bool

    @model_validator(mode="after")
    def retained_integrity(self) -> "RetainedPdf":
        name = self.url.rsplit("/", 1)[-1]
        if self.content_digest != DIGESTS.get(name):
            raise ValueError("Exact authored PDF bytes required")
        if bool(self.authors or self.candidates or self.metadata) != self.excerpts_retained:
            raise ValueError("PDF facts retain their original literal evidence")
        if len(self.model_dump_json().encode()) > 131072:
            raise ValueError("Retained PDF envelope exceeds bounded ceiling")
        return self


def retain_pdf(
    observed: PdfObservation, binding: PdfBinding, *, permit_excerpts: bool
) -> RetainedPdf:
    """Validate facts, not authorization; caller must establish current SQL scope."""
    if type(permit_excerpts) is not bool:
        raise ValueError("Explicit excerpt decision required")
    observed = PdfObservation.model_validate_json(observed.model_dump_json())
    binding = PdfBinding.model_validate_json(binding.model_dump_json())
    facts = bool(observed.authors or observed.candidates or observed.metadata)
    if facts and not permit_excerpts:
        raise ValueError("Locator-only PDF retention is unavailable")
    return RetainedPdf.model_validate(
        {
            **observed.model_dump(),
            "binding": binding.model_dump(),
            "excerpts_retained": facts,
        }
    )


def require_pdf_binding(
    value: RetainedPdf, expected: PdfBinding, *, permit_excerpts: bool
) -> RetainedPdf:
    """Repeat at commit/read release; this comparison cannot replace a SQL fence."""
    value = RetainedPdf.model_validate_json(value.model_dump_json())
    expected = PdfBinding.model_validate_json(expected.model_dump_json())
    if type(permit_excerpts) is not bool or value.binding != expected:
        raise ValueError("Exact current PDF binding required")
    if value.excerpts_retained and not permit_excerpts:
        raise ValueError("Current PDF excerpt retention required")
    return value
