"""Private diagnostic admission, absent from API, queue, CLI and acquisition paths.

A trusted composer must supply a new independently reviewed diagnostic decision.
An existing one-shot parser decision, public availability or XML content cannot
authorize this separate purpose. This is a Python composition boundary, not a
cryptographic authorization system. No actual sample or clearance is bundled.
"""

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from emailmonitor.extraction.sciencedirect import MAX_BYTES
from emailmonitor.parsing.affiliation_diagnostic import AffiliationDiagnostic
from emailmonitor.parsing.affiliation_diagnostic_channel import diagnose_in_container
from emailmonitor.parsing.xml_protocol import XmlExpectation
from emailmonitor.sources.sciencedirect import ArticleIdentifier, Contract

PURPOSE: Final = "one-file-private-affiliation-diagnostic"
REPOSITORY: Final = "https://github.com/elsevierlabs/OA-STM-Corpus"


class PrivateAffiliationDiagnosticManifest(Contract):
    repository: Literal["https://github.com/elsevierlabs/OA-STM-Corpus"]
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    corpus_path: str = Field(pattern=r"^SourceXML/[A-Za-z0-9_-]{1,160}\.norm-xml$")
    evidence_url: str = Field(max_length=512)
    acquired_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    byte_size: int = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_identifier: ArticleIdentifier
    source_profile: Literal["xocs_document"]
    purpose: Literal["one-file-private-affiliation-diagnostic"]

    @model_validator(mode="after")
    def provenance(self) -> "PrivateAffiliationDiagnosticManifest":
        if self.evidence_url != f"{REPOSITORY}/blob/{self.revision}/{self.corpus_path}":
            raise ValueError("Immutable official provenance required")
        acquired = datetime.strptime(self.acquired_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if acquired > datetime.now(UTC):
            raise ValueError("Acquisition timestamp required")
        self.expectation()
        return self

    def expectation(self) -> XmlExpectation:
        return XmlExpectation(
            requested_identifier=self.requested_identifier,
            content_digest=self.sha256,
            source_profile=self.source_profile,
        )

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, repr=False)
class AffiliationDiagnosticRightsDecision:
    """Independent trusted input; never deserialize a manifest into this decision.

    The review must explicitly clear the separate diagnostic purpose for this
    exact manifest, including rights, attribution and conflicting metadata.
    """

    manifest_digest: str
    scope: str
    disposition: Literal["cleared", "unresolved", "denied"]
    review_reference: str


Refusal = Literal["manifest_refused", "rights_refused", "file_refused", "diagnostic_refused"]


@dataclass(frozen=True)
class PrivateAffiliationDiagnosticResult:
    status: Literal["diagnosed", "refused"]
    reasons: tuple[Refusal, ...]
    diagnostic: AffiliationDiagnostic | None = None


def _read_regular(path: Path, manifest: PrivateAffiliationDiagnosticManifest) -> bytes:
    # No-follow every path component, not just the leaf. Nonblocking open also
    # makes a FIFO refuse promptly instead of waiting for a writer.
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ValueError("Private regular file required")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = -1
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size != manifest.byte_size:
            raise ValueError("Bounded private regular file required")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            data = source.read(MAX_BYTES + 1)
            after = os.fstat(source.fileno())
        if len(data) != manifest.byte_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Private sample changed")
        manifest.expectation().check_bytes(data)
        return data
    finally:
        if descriptor != -1:
            os.close(descriptor)
        os.close(directory)


def evaluate_private_affiliation_diagnostic(
    path: Path,
    manifest: PrivateAffiliationDiagnosticManifest,
    rights: AffiliationDiagnosticRightsDecision | None,
) -> PrivateAffiliationDiagnosticResult:
    """Admit once before Docker; return only fixed refusals or validated counters."""
    try:
        if type(manifest) is not PrivateAffiliationDiagnosticManifest or set(
            manifest.__dict__
        ) != set(PrivateAffiliationDiagnosticManifest.model_fields):
            raise ValueError("Diagnostic manifest required")
        manifest = PrivateAffiliationDiagnosticManifest.model_validate(
            manifest.model_dump(warnings="error")
        )
    except Exception:
        return PrivateAffiliationDiagnosticResult("refused", ("manifest_refused",))
    try:
        if (
            type(rights) is not AffiliationDiagnosticRightsDecision
            or rights.disposition != "cleared"
            or rights.scope != PURPOSE
            or rights.manifest_digest != manifest.digest()
            or not isinstance(rights.review_reference, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}", rights.review_reference) is None
        ):
            raise ValueError("Independent diagnostic rights decision required")
    except Exception:
        return PrivateAffiliationDiagnosticResult("refused", ("rights_refused",))
    try:
        data = _read_regular(path, manifest)
    except Exception:
        return PrivateAffiliationDiagnosticResult("refused", ("file_refused",))
    try:
        diagnostic = diagnose_in_container(data, manifest.expectation())
        if type(diagnostic) is not AffiliationDiagnostic or set(diagnostic.__dict__) != set(
            AffiliationDiagnostic.model_fields
        ):
            raise ValueError("Closed diagnostic result required")
        diagnostic = AffiliationDiagnostic.model_validate(diagnostic.model_dump(warnings="error"))
        return PrivateAffiliationDiagnosticResult("diagnosed", (), diagnostic)
    except Exception:
        return PrivateAffiliationDiagnosticResult("refused", ("diagnostic_refused",))
