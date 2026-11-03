"""Private one-file evaluation admission, deliberately absent from API/queue/CLI.

The trusted Python composer supplies an independently reviewed RightsDecision.
This is a composition boundary, not cryptographic authorization against Python
code in this process. A corpus URL, manifest, XML or public availability cannot
issue that decision. No actual sample or rights clearance is bundled here.
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

from emailmonitor.extraction.sciencedirect import MAX_BYTES, Reason, XmlObservation
from emailmonitor.parsing.xml_channel import _parse_in_container
from emailmonitor.parsing.xml_protocol import XmlExpectation
from emailmonitor.sources.sciencedirect import ArticleIdentifier, Contract

PURPOSE: Final = "one-file-private-offline-parser-evaluation"
REPOSITORY: Final = "https://github.com/elsevierlabs/OA-STM-Corpus"


class PrivateSampleManifest(Contract):
    repository: Literal["https://github.com/elsevierlabs/OA-STM-Corpus"]
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    corpus_path: str = Field(pattern=r"^SourceXML/[A-Za-z0-9_-]{1,160}\.norm-xml$")
    evidence_url: str = Field(max_length=512)
    acquired_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    byte_size: int = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_identifier: ArticleIdentifier
    source_profile: Literal["xocs_document"]
    purpose: Literal["one-file-private-offline-parser-evaluation"]

    @model_validator(mode="after")
    def provenance(self) -> "PrivateSampleManifest":
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
class RightsDecision:
    """Trusted-composer input, never deserialized from manifest/XML/API/queue.

    review_reference must identify a private independent review recording rights
    evidence, required attribution, any legacy/conflicting metadata and its exact
    scoped disposition. No license version is inferred. Unresolved review cannot
    use the cleared disposition. The caller is responsible for genuine authority.
    """

    manifest_digest: str
    scope: str
    disposition: Literal["cleared", "unresolved", "denied"]
    review_reference: str


Refusal = Literal["manifest_refused", "rights_refused", "file_refused", "parser_refused"]


@dataclass(frozen=True)
class PrivateSampleResult:
    status: Literal["observed", "no_contact", "partial", "unsupported", "refused"]
    reasons: tuple[Reason | Refusal, ...]
    author_count: int = 0
    candidate_count: int = 0


def _read_regular(path: Path, manifest: PrivateSampleManifest) -> bytes:
    # Traverse each component with no-follow: checking just the leaf would allow
    # symlinked parent directories. Nonblocking open also refuses FIFOs promptly.
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


def evaluate_private_sample(
    path: Path, manifest: PrivateSampleManifest, rights: RightsDecision | None
) -> PrivateSampleResult:
    """One bounded local file → existing OS sandbox → enum/count-only result.

    No acquisition, retention, export, tenant/source grant, or live activation.
    All admission checks precede Docker. Raw content and exceptions never leave
    this wrapper, including when the child produces malformed/misbound output.
    """
    try:
        if type(manifest) is not PrivateSampleManifest or set(manifest.__dict__) != set(
            PrivateSampleManifest.model_fields
        ):
            raise ValueError("Manifest required")
        manifest = PrivateSampleManifest.model_validate(manifest.model_dump(warnings="error"))
    except Exception:
        return PrivateSampleResult("refused", ("manifest_refused",))
    try:
        if (
            type(rights) is not RightsDecision
            or rights.disposition != "cleared"
            or rights.scope != PURPOSE
            or rights.manifest_digest != manifest.digest()
            or not isinstance(rights.review_reference, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}", rights.review_reference) is None
        ):
            raise ValueError("Independent scoped rights decision required")
    except Exception:
        return PrivateSampleResult("refused", ("rights_refused",))
    try:
        data = _read_regular(path, manifest)
    except Exception:
        return PrivateSampleResult("refused", ("file_refused",))
    try:
        expected = manifest.expectation()
        observed = _parse_in_container(data, expected, private_offline=True)
        # Revalidate before reducing even if the transport implementation changes.
        observed = XmlObservation.model_validate(observed.model_dump(warnings="error"))
        expected.check_observation(observed)
        return PrivateSampleResult(
            observed.status,
            tuple(observed.reasons),
            len(observed.authors),
            len(observed.candidates),
        )
    except Exception:
        return PrivateSampleResult("refused", ("parser_refused",))
