"""Correspondence-address observations from supplied article PDF bytes.

Scope: text-layer PDFs (most OA publisher PDFs). The first pages are read with
pypdf (BSD-licensed, already a locked dependency; no MuPDF) under page, byte
and character ceilings. Only literal addresses present in the text layer are
reported:

* An address after a correspondence marker on the same line, or on the line
  directly below a bare marker line, is a ``pdf_correspondence_line``
  observation. Other front-matter addresses are
  ``pdf_front_matter`` observations. Addresses after a References/Bibliography
  heading are ignored.
* An author link is made only when the caller supplies known author names
  (e.g. from Crossref/landing-page metadata) and exactly one surname occurs
  between the previous address on that line (or the bare marker line) and
  this address.
* Grouped notation such as ``{a,b}@lab.example`` and addresses broken across
  lines are *counted* for manual review, never expanded or rejoined.
* Encrypted PDFs, image-only PDFs and parse failures are explicit outcomes.

Isolation note: production must run this behind the network-none parser
worker boundary (EM-008); the preview server calls it in-process.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from io import BytesIO
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from emailmonitor.extraction.jats import attribute_label, find_addresses
from emailmonitor.fetching.safety import FetchDenied

PARSER_VERSION: Literal["pdf-contacts-v1"] = "pdf-contacts-v1"
MAX_BYTES = 20_971_520
DEFAULT_PAGES = 3
MAX_PAGES = 5
MAX_CHARS = 400_000
MAX_CANDIDATES = 100

# Correspondence wording asserts the corresponding-author role; a bare
# "E-mail:"/"Contact:" list only labels addresses and asserts no role.
_CORRESPONDENCE = re.compile(
    r"(\bcorrespond(?:ence|ing)\b|✉|\baddress\s+correspondence\b)", re.IGNORECASE
)
_EMAIL_LABEL = re.compile(r"(\be-?mail(?:\s+address(?:es)?)?\s*:|\bcontact\s*:)", re.IGNORECASE)
_REFERENCES = re.compile(r"^\s*(references|bibliography|literature\s+cited)\s*$", re.IGNORECASE)
# Linear: the first class excludes the comma, so no ambiguous split points.
_GROUPED = re.compile(r"[{(\[][^{}()\[\]@,]{1,200}(?:,[^{}()\[\]@,]{1,200}){1,20}[})\]]\s*@")
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+[A-Za-z0-9])")

PdfBasis = Literal["pdf_correspondence_surname", "pdf_email_label_surname", "unmatched"]
PdfRegion = Literal["pdf_correspondence_line", "pdf_email_line", "pdf_front_matter"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PdfContactCandidate(Contract):
    raw_address: str = Field(min_length=3, max_length=320)
    page: int = Field(ge=1, le=MAX_PAGES)
    line: int = Field(ge=1)
    region: PdfRegion
    author_name: str | None = Field(default=None, max_length=300)
    author_position: int | None = Field(default=None, ge=1, le=100)
    association_basis: PdfBasis
    association_status: Literal["needs_review", "unmatched"]
    excerpt: str = Field(max_length=300)

    @model_validator(mode="after")
    def consistent(self) -> PdfContactCandidate:
        unmatched = self.association_basis == "unmatched"
        if (self.author_name is None) != (self.author_position is None):
            raise ValueError("author name and position must agree")
        if unmatched != (self.author_name is None) or unmatched != (
            self.association_status == "unmatched"
        ):
            raise ValueError("association basis, author and status disagree")
        return self


class PdfContactObservation(Contract):
    parser_version: Literal["pdf-contacts-v1"] = PARSER_VERSION
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "image_only", "encrypted_refused", "unreadable"]
    reason: str | None = Field(default=None, max_length=200)
    page_count: int = Field(default=0, ge=0)
    pages_read: int = Field(default=0, ge=0, le=MAX_PAGES)
    title: str | None = Field(default=None, max_length=1000)
    doi: str | None = Field(default=None, max_length=256)
    candidates: tuple[PdfContactCandidate, ...] = Field(
        default_factory=tuple, max_length=MAX_CANDIDATES
    )
    grouped_address_notations: int = Field(default=0, ge=0)
    possibly_wrapped_addresses: int = Field(default=0, ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def consistent(self) -> PdfContactObservation:
        if (self.status == "observed") != bool(self.candidates):
            raise ValueError("status disagrees with candidates")
        return self


def _lines(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).replace("­", "")
    return [" ".join(line.split()) for line in normalized.splitlines()]


def parse_pdf_contacts(
    data: bytes,
    known_authors: Sequence[str] = (),
    max_pages: int = DEFAULT_PAGES,
) -> PdfContactObservation:
    """Observe correspondence addresses in the first ``max_pages`` pages."""
    if not 1 <= max_pages <= MAX_PAGES:
        raise FetchDenied("pdf_page_window_denied")
    if len(data) > MAX_BYTES:
        raise FetchDenied("pdf_byte_limit_exceeded")
    if not data.lstrip().startswith(b"%PDF-"):
        raise FetchDenied("not_a_pdf")
    digest = hashlib.sha256(data).hexdigest()
    authors = [a.strip()[:300] for a in known_authors[:100] if a.strip()]

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            return PdfContactObservation(
                content_digest=digest, status="encrypted_refused", reason="encrypted_pdf"
            )
        page_count = len(reader.pages)
        title_raw = reader.metadata.title if reader.metadata else None
        texts: list[str] = []
        total = 0
        truncated = False
        for page in reader.pages[:max_pages]:
            text = page.extract_text() or ""
            if total + len(text) > MAX_CHARS:
                text = text[: MAX_CHARS - total]
                truncated = True
            total += len(text)
            texts.append(text)
            if truncated:
                break
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        return PdfContactObservation(
            content_digest=digest,
            status="unreadable",
            reason=type(exc).__name__[:200],
        )

    pages_read = len(texts)
    if not any(t.strip() for t in texts):
        return PdfContactObservation(
            content_digest=digest,
            status="image_only",
            reason="no_text_layer",
            page_count=page_count,
            pages_read=pages_read,
        )

    candidates: list[PdfContactCandidate] = []
    seen: set[str] = set()
    grouped = 0
    wrapped = 0
    doi: str | None = None
    names = list(enumerate(authors, start=1))
    for page_number, text in enumerate(texts, start=1):
        lines = _lines(text)
        carried: PdfRegion | None = None
        carried_text = ""
        for index, line in enumerate(lines):
            if _REFERENCES.match(line):
                break
            if doi is None:
                match = _DOI.search(line)
                if match:
                    doi = match.group(1).lower()
            grouped_spans = [(m.start(), m.end()) for m in _GROUPED.finditer(line)]
            grouped += len(grouped_spans)
            last_token = line.rsplit(" ", 1)[-1] if line else ""
            if "@" in last_token and last_token.endswith(("@", ".", "-")):
                wrapped += 1
            correspondence = _CORRESPONDENCE.search(line)
            email_label = _EMAIL_LABEL.search(line)
            found = find_addresses(line)
            # A marker line without an address of its own labels the next line only.
            inherited, inherited_text = carried, carried_text
            carried = None
            carried_text = ""
            if not found and (correspondence or email_label):
                carried = "pdf_correspondence_line" if correspondence else "pdf_email_line"
                carried_text = line
            boundary = 0
            for start, address in found:
                end = start + len(address)
                in_group = any(lo < end and start < hi for lo, hi in grouped_spans)
                if in_group or address.casefold() in seen or len(candidates) >= MAX_CANDIDATES:
                    boundary = end
                    continue
                seen.add(address.casefold())
                region: PdfRegion
                if correspondence and correspondence.start() < start:
                    region = "pdf_correspondence_line"
                elif email_label and email_label.start() < start:
                    region = "pdf_email_line"
                elif inherited is not None:
                    region = inherited
                else:
                    region = "pdf_front_matter"
                text_for_label = line
                offset = 0
                if inherited is not None and region == inherited and boundary == 0:
                    text_for_label = inherited_text + " " + line
                    offset = len(inherited_text) + 1
                owner: int | None = None
                if region != "pdf_front_matter":
                    owner, _kind, label_end = attribute_label(
                        text_for_label,
                        start + offset,
                        end + offset,
                        boundary + offset if boundary else 0,
                        names,
                    )
                    boundary = label_end - offset
                else:
                    boundary = end
                basis: PdfBasis = "unmatched"
                if owner is not None:
                    basis = (
                        "pdf_correspondence_surname"
                        if region == "pdf_correspondence_line"
                        else "pdf_email_label_surname"
                    )
                context = (inherited_text + " " + line) if inherited is not None else line
                candidates.append(
                    PdfContactCandidate(
                        raw_address=address,
                        page=page_number,
                        line=index + 1,
                        region=region,
                        author_name=authors[owner - 1] if owner is not None else None,
                        author_position=owner,
                        association_basis=basis,
                        association_status="needs_review" if owner is not None else "unmatched",
                        excerpt=context[:300],
                    )
                )

    title = " ".join(str(title_raw).split())[:1000] if title_raw else None
    return PdfContactObservation(
        content_digest=digest,
        status="observed" if candidates else "no_contact",
        page_count=page_count,
        pages_read=pages_read,
        title=title or None,
        doi=doi,
        candidates=tuple(candidates),
        grouped_address_notations=grouped,
        possibly_wrapped_addresses=wrapped,
        truncated=truncated,
    )
