"""Bounded, versioned XML byte protocol; no tenant or credential authority enters it."""

import hashlib
import json
from typing import BinaryIO, Literal

from pydantic import Field, model_validator

from emailmonitor.extraction.sciencedirect import MAX_BYTES, XmlObservation, parse_article
from emailmonitor.sources.sciencedirect import ArticleIdentifier, Contract, article_path

MAX_HEADER = 1024


class XmlExpectation(Contract):
    protocol: Literal["xml-input-v1"] = "xml-input-v1"
    requested_identifier: ArticleIdentifier
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_profile: Literal["article_retrieval_response", "xocs_document"]

    @model_validator(mode="after")
    def canonical_identifier(self) -> "XmlExpectation":
        article_path(self.requested_identifier)
        return self

    def check_bytes(self, data: bytes) -> None:
        if (
            type(data) is not bytes
            or not 1 <= len(data) <= MAX_BYTES
            or hashlib.sha256(data).hexdigest() != self.content_digest
        ):
            raise ValueError("Bounded matching XML provenance required")

    def check_observation(self, observed: XmlObservation) -> None:
        if (
            observed.requested_identifier != self.requested_identifier
            or observed.content_digest != self.content_digest
            or observed.source_profile != self.source_profile
        ):
            raise ValueError("Parser provenance mismatch")


def encode_input(data: bytes, expected: XmlExpectation) -> bytes:
    expected = XmlExpectation.model_validate(expected.model_dump())
    expected.check_bytes(data)
    header = expected.model_dump_json().encode("ascii") + b"\n"
    if len(header) > MAX_HEADER:
        raise ValueError("Bounded XML input header required")
    return header + data


def read_input(stream: BinaryIO) -> tuple[bytes, XmlExpectation]:
    """A short JSON line, then exact capped raw bytes. No base64 copy amplification."""
    header = stream.readline(MAX_HEADER + 1)
    if len(header) > MAX_HEADER or not header.endswith(b"\n"):
        raise ValueError("Bounded XML input header required")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate parser input field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("Invalid parser input number")

    # Decode once with duplicate/nonfinite checks, then strict JSON-mode UUID-free types.
    document = json.loads(header.decode("ascii"), object_pairs_hook=pairs, parse_constant=constant)
    expected = XmlExpectation.model_validate_json(json.dumps(document))
    if encode_header(expected) != header:
        raise ValueError("Canonical parser input header required")
    data = stream.read(MAX_BYTES + 1)
    expected.check_bytes(data)
    return data, expected


def encode_header(expected: XmlExpectation) -> bytes:
    return expected.model_dump_json().encode("ascii") + b"\n"


def parse_input(stream: BinaryIO) -> XmlObservation:
    """Called only after the worker's kernel/profile checks; pure testable protocol."""
    data, expected = read_input(stream)
    observed = parse_article(data, expected.requested_identifier)
    expected.check_observation(observed)
    return observed
