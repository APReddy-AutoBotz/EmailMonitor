"""Canonical authored-PDF byte protocol, with no filesystem or network authority."""

import hashlib
from typing import BinaryIO, Literal

from pydantic import Field, model_validator

from emailmonitor.config import Settings
from emailmonitor.extraction.html import Fact
from emailmonitor.extraction.pdf import PdfObservation, parse_pdf
from emailmonitor.extraction.pdf_fixture import DIGESTS

MAX_HEADER = 1024
MAX_BYTES = 262144


class PdfExpectation(Fact):
    protocol: Literal["authored-pdf-input-v1"] = "authored-pdf-input-v1"
    url: str = Field(max_length=200)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def authored(self) -> "PdfExpectation":
        registry = {"https://synthetic.publisher.example/" + k: v for k, v in DIGESTS.items()}
        if registry.get(self.url) != self.content_digest:
            raise ValueError("Exact authored PDF identifier and digest required")
        return self

    def check_bytes(self, data: bytes) -> None:
        if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
            raise ValueError("Bounded PDF bytes required")
        if hashlib.sha256(data).hexdigest() != self.content_digest:
            raise ValueError("Authored PDF digest mismatch")

    def check_observation(self, value: PdfObservation) -> None:
        if value.url != self.url or value.content_digest != self.content_digest:
            raise ValueError("PDF parser provenance mismatch")


def encode_input(data: bytes, expected: PdfExpectation) -> bytes:
    expected = PdfExpectation.model_validate(expected.model_dump())
    expected.check_bytes(data)
    return expected.model_dump_json().encode("ascii") + b"\n" + data


def read_input(stream: BinaryIO) -> tuple[bytes, PdfExpectation]:
    header = stream.readline(MAX_HEADER + 1)
    if len(header) > MAX_HEADER or not header.endswith(b"\n"):
        raise ValueError("Bounded PDF header required")
    expected = PdfExpectation.model_validate_json(header)
    # Exact canonical encoding also rejects duplicate/extra fields and whitespace variants.
    if expected.model_dump_json().encode("ascii") + b"\n" != header:
        raise ValueError("Canonical PDF header required")
    data = stream.read(MAX_BYTES + 1)
    expected.check_bytes(data)
    return data, expected


def parse_input(stream: BinaryIO) -> PdfObservation:
    data, expected = read_input(stream)
    observed = parse_pdf(Settings(environment="test", fixture_mode=True), expected.url, data)
    expected.check_observation(observed)
    return observed
