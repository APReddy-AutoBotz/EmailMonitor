"""Bounded, versioned JATS byte protocol for the network-none parser sandbox (OA-029).

Separate from ``xml_protocol`` (whose bytes are pinned by a reviewed workflow): a
short canonical JSON header line naming the PMCID and SHA-256, then the exact raw
bytes. No tenant, credential or URL authority enters the sandbox.
"""

from __future__ import annotations

import hashlib
import json
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.extraction.jats import MAX_BYTES, JatsObservation, parse_jats_xml
from emailmonitor.sources.openaccess import PmcIdentifier

MAX_HEADER = 512


class JatsExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    protocol: Literal["jats-input-v1"] = "jats-input-v1"
    requested_identifier: PmcIdentifier
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def check_bytes(self, data: bytes) -> None:
        if (
            type(data) is not bytes
            or not 1 <= len(data) <= MAX_BYTES
            or hashlib.sha256(data).hexdigest() != self.content_digest
        ):
            raise ValueError("Bounded matching JATS provenance required")

    def check_observation(self, observed: JatsObservation) -> None:
        if (
            observed.requested_identifier != self.requested_identifier
            or observed.content_digest != self.content_digest
        ):
            raise ValueError("Parser provenance mismatch")


def encode_header(expected: JatsExpectation) -> bytes:
    return expected.model_dump_json().encode("ascii") + b"\n"


def encode_input(data: bytes, expected: JatsExpectation) -> bytes:
    expected = JatsExpectation.model_validate(expected.model_dump())
    expected.check_bytes(data)
    header = encode_header(expected)
    if len(header) > MAX_HEADER:
        raise ValueError("Bounded JATS input header required")
    return header + data


def read_input(stream: BinaryIO) -> tuple[bytes, JatsExpectation]:
    header = stream.readline(MAX_HEADER + 1)
    if len(header) > MAX_HEADER or not header.endswith(b"\n"):
        raise ValueError("Bounded JATS input header required")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate parser input field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("Invalid parser input number")

    document = json.loads(header.decode("ascii"), object_pairs_hook=pairs, parse_constant=constant)
    expected = JatsExpectation.model_validate_json(json.dumps(document))
    if encode_header(expected) != header:
        raise ValueError("Canonical parser input header required")
    data = stream.read(MAX_BYTES + 1)
    expected.check_bytes(data)
    return data, expected


def parse_input(stream: BinaryIO) -> JatsObservation:
    """Called only after the worker's kernel/profile checks; pure testable protocol."""
    data, expected = read_input(stream)
    observed = parse_jats_xml(data, expected.requested_identifier)
    expected.check_observation(observed)
    return observed
