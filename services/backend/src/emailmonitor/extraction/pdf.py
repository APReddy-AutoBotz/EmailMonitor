"""Bounded synthetic PDF bytes to observed facts, with no acquisition or OCR.

Coordinates are actual text-fragment anchors in PDF user space. Evidence regions
are the actual full CropBox, deliberately coarse, never fabricated glyph boxes.
The trusted worker owns authorization; this adapter receives bytes and cannot
fetch URLs, execute document actions, choose credentials or accept identities.
"""

import hashlib
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypdf import Configuration, PdfReader, apply_configuration, mult
from pypdf.errors import DependencyError, LimitReachedError, PyPdfError
from pypdf.generic import DictionaryObject

from emailmonitor.config import Settings
from emailmonitor.extraction.html import MetadataValues
from emailmonitor.fetching.safety import FetchDenied, classify_url

HOST = "synthetic.publisher.example"
NAMES = frozenset(
    {
        "article-a.pdf",
        "article-b.pdf",
        "wrapped.pdf",
        "ambiguous.pdf",
        "no-contact.pdf",
        "scanned.pdf",
        "encrypted.pdf",
        "page-cap.pdf",
        "corrupt.pdf",
    }
)
EMAIL = re.compile(r"(?<![\w@])[^\s<>;,\[\]@]+@[^\s<>;,\[\]@]+\.[^\s<>;,\[\]@]+")


@dataclass(frozen=True)
class PdfLimits:
    max_bytes: int = 262144
    max_pages: int = 4
    max_fragments: int = 256
    max_characters: int = 8192
    max_stream_bytes: int = 65536
    total_seconds: float = 3

    def __post_init__(self) -> None:
        for field, ceiling in (
            ("max_bytes", 262144),
            ("max_pages", 4),
            ("max_fragments", 256),
            ("max_characters", 8192),
            ("max_stream_bytes", 65536),
        ):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("PDF limit cannot relax the synthetic platform ceiling")
        if type(self.total_seconds) not in (int, float) or not 0 < self.total_seconds <= 3:
            raise ValueError("Finite bounded PDF deadline required")


METADATA_LABELS: tuple[tuple[Literal["title", "journal", "publication_date", "doi"], str], ...] = (
    ("title", "Title:"),
    ("journal", "Journal:"),
    ("publication_date", "Date:"),
    ("doi", "DOI:"),
)
DEFAULT_LIMITS = PdfLimits()


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PdfEvidence(Fact):
    page: int = Field(ge=1, le=4)
    locator: str = Field(pattern=r"^page:[1-4]:fragment:[0-9]{1,3}$")
    anchor: tuple[float, float]
    region: tuple[float, float, float, float]
    coordinate_units: Literal["pdf_points"] = "pdf_points"
    coordinate_origin: Literal["bottom_left"] = "bottom_left"
    region_precision: Literal["full_cropbox_not_glyph_bbox"] = "full_cropbox_not_glyph_bbox"
    excerpt: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def geometry(self) -> "PdfEvidence":
        if not all(math.isfinite(v) for v in (*self.anchor, *self.region)):
            raise ValueError("Finite evidence geometry required")
        if int(self.locator.split(":")[1]) != self.page:
            raise ValueError("Locator page must agree with evidence page")
        x0, y0, x1, y1 = self.region
        if not x0 <= self.anchor[0] <= x1 or not y0 <= self.anchor[1] <= y1 or x0 >= x1 or y0 >= y1:
            raise ValueError("Actual anchor must lie within ordered page region")
        return self


class PdfAuthor(Fact):
    position: int = Field(ge=1, le=100)
    display_name: str = Field(min_length=1, max_length=200)
    marker: str = Field(pattern=r"^[1-9][0-9]?$", max_length=2)
    first: bool
    affiliations: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=20
    )
    corresponding: bool | None = None
    evidence: list[PdfEvidence] = Field(min_length=1, max_length=10)


class PdfCandidate(Fact):
    raw_address: str = Field(min_length=3, max_length=320)
    author_positions: list[Annotated[int, Field(ge=1, le=100)]] = Field(max_length=100)
    association_status: Literal["unmatched", "needs_review"]
    technical_status: Literal["not_checked"] = "not_checked"
    delivery_status: Literal["unverified"] = "unverified"
    outreach_eligibility: Literal["not_assessed"] = "not_assessed"
    reconstruction: Literal["literal", "adjacent_line_wrap"]
    evidence: list[PdfEvidence] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def literal_provenance(self) -> "PdfCandidate":
        if self.reconstruction == "literal":
            if not any(self.raw_address in e.excerpt for e in self.evidence):
                raise ValueError("Observed raw address must appear in actual evidence")
        else:
            if len(self.evidence) != 3:
                raise ValueError("Wrapped address requires header and two actual lines")
            a, b = self.evidence[1:]
            if (
                self.raw_address != a.excerpt.strip() + b.excerpt.strip()
                or a.page != b.page
                or abs(a.anchor[0] - b.anchor[0]) > 2
                or not 0 < a.anchor[1] - b.anchor[1] <= 16
            ):
                raise ValueError("Only actual adjacent same-column text may be joined")
        return self


class PdfMetadata(Fact):
    date_type: Literal["unspecified"] = "unspecified"
    field: Literal["title", "journal", "publication_date", "doi"]
    value: str = Field(min_length=1, max_length=300)
    evidence: PdfEvidence


class PdfObservation(Fact):
    schema_version: Literal["1.0"] = "1.0"
    parser_version: Literal["pypdf-6.20.1-synthetic-v1"] = "pypdf-6.20.1-synthetic-v1"
    route: Literal["pdf"] = "pdf"
    url: str = Field(max_length=200)
    content_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "partial", "unsupported"]
    reason: Literal[
        "complete",
        "page_cap",
        "byte_cap",
        "encrypted",
        "corrupt",
        "image_only_or_no_extractable_text",
        "unsupported_geometry",
        "unsupported_font_or_structure",
        "resource_limit",
        "deadline",
        "pdf_disabled",
    ]
    pages_total: int | None = Field(default=None, ge=1, le=64)
    pages_inspected: int = Field(ge=0, le=4)
    complete_scan: bool
    authors: list[PdfAuthor] = Field(default_factory=list, max_length=100)
    candidates: list[PdfCandidate] = Field(default_factory=list, max_length=100)
    metadata: list[PdfMetadata] = Field(default_factory=list, max_length=20)
    preferred_metadata: MetadataValues
    identity_association_implemented: Literal[False] = False
    ocr_implemented: Literal[False] = False

    @field_validator("url")
    @classmethod
    def registered_url(cls, value: str) -> str:
        try:
            safe = classify_url(value, frozenset({HOST}))
        except FetchDenied:
            raise ValueError("Registered synthetic PDF identifier required") from None
        if safe.normalized != value or value not in {f"https://{HOST}/" + name for name in NAMES}:
            raise ValueError("Registered synthetic PDF identifier required")
        return value

    @field_validator("identity_association_implemented", "ocr_implemented", mode="before")
    @classmethod
    def unavailable(cls, value: object) -> object:
        if type(value) is not bool or value is not False:
            raise ValueError("Unavailable operation requires boolean false")
        return value

    @model_validator(mode="after")
    def consistent(self) -> "PdfObservation":
        early_refusal = self.status == "unsupported" and self.reason in ("byte_cap", "pdf_disabled")
        if (self.content_digest is None) != early_refusal:
            raise ValueError("Only unprocessed byte-cap/disabled inputs omit a full digest")
        values = {
            field: next((m.value for m in self.metadata if m.field == field), None)
            for field in ("title", "journal", "publication_date", "doi")
        }
        if self.preferred_metadata != MetadataValues.model_validate(values):
            raise ValueError("PDF metadata must retain observed facts and missing nulls")
        if self.status != "unsupported" and not self.authors:
            raise ValueError("Supported observations require ordered author evidence")
        if [a.position for a in self.authors] != list(range(1, len(self.authors) + 1)) or any(
            a.first != (a.position == 1) for a in self.authors
        ):
            raise ValueError("Ordered authors and first role must agree")
        if any(
            len(set(c.author_positions)) != len(c.author_positions)
            or any(p > len(self.authors) for p in c.author_positions)
            or c.association_status != ("needs_review" if c.author_positions else "unmatched")
            for c in self.candidates
        ):
            raise ValueError("Unaccepted structural author references must exist")
        if self.complete_scan != (
            self.pages_total is not None and self.pages_inspected == self.pages_total
        ):
            raise ValueError("Complete scan requires every actual page")
        if self.status == "unsupported" and self.reason in ("complete", "page_cap"):
            raise ValueError("Unsupported reason cannot claim completeness or partial scan")
        if self.status == "unsupported" and (
            self.authors
            or self.candidates
            or self.metadata
            or self.complete_scan
            or self.pages_inspected != 0
        ):
            raise ValueError("Unsupported input cannot assert completed observations")
        if self.status == "observed" and (
            not self.candidates or not self.complete_scan or self.reason != "complete"
        ):
            raise ValueError("Observed complete outcome requires actual candidates")
        if self.status == "no_contact" and (
            self.candidates
            or not self.authors
            or not self.complete_scan
            or self.reason != "complete"
        ):
            raise ValueError("No-contact claim requires fully inspected supported document")
        if self.status == "partial" and (
            self.reason != "page_cap"
            or self.complete_scan
            or not self.pages_total
            or self.pages_inspected >= self.pages_total
        ):
            raise ValueError("Partial page cap must preserve unseen pages")
        if (
            any(e.page > self.pages_inspected for a in self.authors for e in a.evidence)
            or any(e.page > self.pages_inspected for c in self.candidates for e in c.evidence)
            or any(m.evidence.page > self.pages_inspected for m in self.metadata)
        ):
            raise ValueError("Evidence cannot refer to an uninspected page")
        return self


@dataclass(frozen=True)
class Fragment:
    evidence: PdfEvidence
    size: float


class Refusal(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def configuration(limits: PdfLimits) -> Configuration:
    return Configuration(
        maximum_declared_stream_length=limits.max_stream_bytes,
        array_based_stream_maximum_output_length=limits.max_stream_bytes,
        jbig2_maximum_output_length=limits.max_stream_bytes,
        lzw_maximum_output_length=limits.max_stream_bytes,
        run_length_maximum_output_length=limits.max_stream_bytes,
        zlib_maximum_output_length=limits.max_stream_bytes,
        zlib_maximum_recovery_input_length=limits.max_stream_bytes,
        brotli_maximum_output_length=limits.max_stream_bytes,
        flate_maximum_columns=4096,
        flate_maximum_row_length=limits.max_stream_bytes,
        image_maximum_buffer_size=limits.max_stream_bytes,
        stream_filters_maximum_length=4,
        stream_decoding_work_maximum_length=limits.max_stream_bytes * 4,
        xmp_maximum_input_length=limits.max_stream_bytes,
        xmp_maximum_element_count=256,
        outline_maximum_entries=64,
        outline_maximum_depth=8,
        page_tree_maximum_entries=64,
        page_tree_maximum_depth=16,
        xform_maximum_invocations_per_extraction=1,
        jbig2dec_binary=None,
    )


def _facts(
    fragments: list[Fragment],
) -> tuple[list[PdfAuthor], list[PdfCandidate], list[PdfMetadata]]:
    reference_cutoffs = {
        page: max(
            f.evidence.anchor[1]
            for f in fragments
            if f.evidence.page == page and f.evidence.excerpt == "References"
        )
        for page in {f.evidence.page for f in fragments if f.evidence.excerpt == "References"}
    }
    fragments = [
        f
        for f in fragments
        if f.evidence.anchor[1] > reference_cutoffs.get(f.evidence.page, -1)
        and not f.evidence.excerpt.startswith(("Support:", "Copyright:", "Advertisement:"))
    ]
    headers = [f for f in fragments if f.evidence.excerpt.startswith("Authors:")]
    if not headers:
        raise Refusal("unsupported_font_or_structure")
    header = headers[0]
    header_parts = [header]
    value = header.evidence.excerpt.removeprefix("Authors:").strip()
    if not re.search(r"\[[1-9][0-9]?\]", value):
        raised = sorted(
            [
                f
                for f in fragments
                if f.evidence.page == header.evidence.page
                and f.evidence.anchor[0] > header.evidence.anchor[0]
                and -1 <= f.evidence.anchor[1] - header.evidence.anchor[1] <= 8
            ],
            key=lambda f: f.evidence.anchor[0],
        )
        if len(raised) > 9:
            raise Refusal("unsupported_font_or_structure")
        for f in raised:
            text = f.evidence.excerpt
            delta = f.evidence.anchor[1] - header.evidence.anchor[1]
            if delta > 1 and f.size < header.size and re.fullmatch(r"[1-9][0-9]?", text):
                value += " [" + text + "]"
            elif abs(delta) <= 1 and text.startswith(";"):
                value += text
            else:
                raise Refusal("unsupported_font_or_structure")
            header_parts.append(f)
    entries = [entry.strip() for entry in value.split(";")]
    authors: list[PdfAuthor] = []
    for position, entry in enumerate(entries, 1):
        matched = re.fullmatch(r"(.{1,200}?) \[([1-9][0-9]?)\]", entry)
        if not matched or position > 100:
            raise Refusal("unsupported_font_or_structure")
        authors.append(
            PdfAuthor(
                position=position,
                display_name=matched[1],
                marker=matched[2],
                first=position == 1,
                evidence=[f.evidence for f in header_parts],
            )
        )
    # Repeated headers must identify the same ordered instances, not add authors.
    if any(f.evidence.excerpt != header.evidence.excerpt for f in headers[1:]):
        raise Refusal("unsupported_font_or_structure")
    if len({a.marker for a in authors}) != len(authors):
        raise Refusal("unsupported_font_or_structure")
    metadata: list[PdfMetadata] = []
    for f in fragments:
        for field, label in METADATA_LABELS:
            if f.evidence.excerpt.startswith(label) and len(metadata) < 20:
                metadata.append(
                    PdfMetadata(
                        field=field,
                        value=f.evidence.excerpt[len(label) :].strip(),
                        evidence=f.evidence,
                    )
                )
    for f in fragments:
        affiliation = re.fullmatch(r"Affiliation \[([1-9][0-9]?)\]: (.{1,300})", f.evidence.excerpt)
        if affiliation:
            for index, author in enumerate(authors):
                if author.marker == affiliation[1]:
                    if len(author.affiliations) >= 20 or len(author.evidence) >= 10:
                        raise Refusal("resource_limit")
                    authors[index] = author.model_copy(
                        update={
                            "affiliations": [*author.affiliations, affiliation[2]],
                            "evidence": [*author.evidence, f.evidence],
                        }
                    )
    candidates: list[PdfCandidate] = []
    for first in fragments:
        text = first.evidence.excerpt
        matched = re.fullmatch(r"Correspondence(?: \[([1-9][0-9]?)\])?: (.{1,200}?);(.*)", text)
        if not matched:
            continue
        marker, name, tail = matched.groups()
        positions = [
            a.position
            for a in authors
            if a.display_name == name and (marker is None or a.marker == marker)
        ]
        if len(positions) != 1:
            positions = []
        if positions:
            a = authors[positions[0] - 1]
            authors[positions[0] - 1] = a.model_copy(
                update={"corresponding": True, "evidence": [*a.evidence, first.evidence][:10]}
            )
        chosen = [first]
        address_text = tail.strip()
        # Only immediately adjacent, same-column lines may continue this block.
        adjacent = sorted(
            [
                f
                for f in fragments
                if f.evidence.page == first.evidence.page
                and abs(f.evidence.anchor[0] - first.evidence.anchor[0]) <= 2
                and 0 < first.evidence.anchor[1] - f.evidence.anchor[1] <= 30
            ],
            key=lambda f: -f.evidence.anchor[1],
        )
        if not address_text and adjacent:
            following = adjacent[0]
            if first.evidence.anchor[1] - following.evidence.anchor[1] <= 16:
                following_text = following.evidence.excerpt.strip()
                if EMAIL.fullmatch(following_text) or re.fullmatch(
                    r"[^\s<>;,\[\]@]+@", following_text
                ):
                    address_text = following_text
                    chosen.append(following)
                if address_text.endswith("@") and len(adjacent) > 1:
                    end = adjacent[1]
                    if following.evidence.anchor[1] - end.evidence.anchor[1] <= 16 and re.fullmatch(
                        r"[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", end.evidence.excerpt.strip()
                    ):
                        address_text += end.evidence.excerpt.strip()
                        chosen.append(end)
        addresses = EMAIL.findall(address_text)
        for address in addresses:
            if len(address) > 320 or len(candidates) >= 100:
                raise Refusal("resource_limit")
            candidates.append(
                PdfCandidate(
                    raw_address=address,
                    author_positions=positions,
                    association_status="needs_review" if positions else "unmatched",
                    reconstruction="adjacent_line_wrap" if len(chosen) == 3 else "literal",
                    evidence=[f.evidence for f in chosen],
                )
            )
    return authors, candidates, metadata


def parse_pdf(
    settings: Settings,
    url: str,
    data: bytes,
    *,
    limits: PdfLimits = DEFAULT_LIMITS,
    allow_pdf: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> PdfObservation:
    if settings.environment != "test" or not settings.fixture_mode:
        raise FetchDenied("Synthetic PDF parser requires explicit test fixture mode")
    if type(data) is not bytes or type(allow_pdf) is not bool:
        raise ValueError("Immutable bytes and explicit PDF option required")
    PdfObservation.registered_url(url)
    early_reason = (
        "pdf_disabled" if not allow_pdf else "byte_cap" if len(data) > limits.max_bytes else None
    )
    digest = None if early_reason else hashlib.sha256(data).hexdigest()
    base = {
        "url": url,
        "content_digest": digest,
        "pages_inspected": 0,
        "complete_scan": False,
        "preferred_metadata": MetadataValues(),
    }
    # Validate the identifier even on refusal; no response reflects arbitrary URLs.
    PdfObservation.model_validate(
        {**base, "status": "unsupported", "reason": early_reason or "corrupt"}
    )

    def refused(reason: str) -> PdfObservation:
        return PdfObservation.model_validate({**base, "status": "unsupported", "reason": reason})

    if early_reason:
        return refused(early_reason)
    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        return refused("corrupt")
    deadline = clock() + limits.total_seconds

    def check() -> None:
        if clock() >= deadline:
            raise Refusal("deadline")

    fragments: list[Fragment] = []
    characters = 0
    try:
        with apply_configuration(configuration(limits)):
            check()
            reader = PdfReader(BytesIO(data), strict=True)
            check()
            # Reader initialization may test only the empty password; never call
            # decrypt(), accept a password, or inspect pages of encrypted inputs.
            if reader.is_encrypted:
                return refused("encrypted")
            total = len(reader.pages)
            if not 1 <= total <= 64:
                raise Refusal("resource_limit")
            inspected = min(total, limits.max_pages)
            for number in range(1, inspected + 1):
                check()
                page = reader.pages[number - 1]
                if page.rotation != 0 or page.user_unit != 1:
                    raise Refusal("unsupported_geometry")
                region = tuple(float(value) for value in page.cropbox)
                if (
                    len(region) != 4
                    or not all(math.isfinite(value) and 0 <= value <= 2000 for value in region)
                    or region[0] >= region[2]
                    or region[1] >= region[3]
                ):
                    raise Refusal("unsupported_geometry")
                index = 0
                resources = page.get("/Resources", DictionaryObject())

                def operand(
                    operator: bytes,
                    args: list[object],
                    cm: list[float],
                    tm: list[float],
                    resources: DictionaryObject = resources,
                ) -> None:
                    check()
                    if operator == b"Do":
                        xobjects = resources.get("/XObject", DictionaryObject())
                        if args and (item := xobjects.get(str(args[0]))) is not None:
                            if item.get_object().get("/Subtype") == "/Form":
                                raise Refusal("unsupported_geometry")
                    # Visitors do not include rise/width/spacing in their anchor.
                    # Keep this profile to default text state and simple Tj shows;
                    # adjusted/implicit shows cannot support our visual adjacency.
                    defaults = {b"Ts": 0, b"Tz": 100, b"Tc": 0, b"Tw": 0}
                    if operator in defaults and (len(args) != 1 or args[0] != defaults[operator]):
                        raise Refusal("unsupported_geometry")
                    if operator in (b"TJ", b"'", b'"'):
                        raise Refusal("unsupported_geometry")
                    if operator in (b"gs", b"W", b"W*", b"rg", b"RG", b"g", b"G", b"k", b"K") or (
                        operator == b"Tr" and args and args[0] != 0
                    ):
                        raise Refusal("unsupported_geometry")

                def visitor(
                    value: str,
                    cm: list[float],
                    tm: list[float],
                    font: DictionaryObject | None,
                    size: float,
                    region: tuple[float, ...] = region,
                    number: int = number,
                ) -> None:
                    nonlocal index, characters
                    check()
                    text = value.strip()
                    if not text:
                        return
                    if (
                        font is None
                        or font.get("/Subtype") != "/Type1"
                        or font.get("/BaseFont") not in ("/Courier", "/Helvetica", "/Times-Roman")
                        or font.get("/Encoding") != "/WinAnsiEncoding"
                        or "/ToUnicode" in font
                        or "/FontDescriptor" in font
                    ):
                        raise Refusal("unsupported_font_or_structure")
                    if (
                        len(cm) != 6
                        or len(tm) != 6
                        or cm[:4] != [1, 0, 0, 1]
                        or tm[:4] != [1, 0, 0, 1]
                        or not math.isfinite(size)
                        or not 1 <= size <= 72
                    ):
                        raise Refusal("unsupported_geometry")
                    matrix = mult(tm, cm)
                    x, y = float(matrix[4]), float(matrix[5])
                    if not math.isfinite(x) or not math.isfinite(y):
                        raise Refusal("unsupported_geometry")
                    if not region[0] <= x <= region[2] or not region[1] <= y <= region[3]:
                        return
                    index += 1
                    characters += len(text)
                    if (
                        index > limits.max_fragments
                        or len(fragments) >= limits.max_fragments
                        or len(text) > 512
                        or characters > limits.max_characters
                    ):
                        raise Refusal("resource_limit")
                    evidence = PdfEvidence(
                        page=number,
                        locator=f"page:{number}:fragment:{index}",
                        anchor=(x, y),
                        region=(region[0], region[1], region[2], region[3]),
                        excerpt=text,
                    )
                    fragments.append(Fragment(evidence, size))

                page.extract_text(visitor_text=visitor, visitor_operand_before=operand)
                check()
            if not fragments:
                return refused("image_only_or_no_extractable_text")
            authors, candidates, metadata = _facts(fragments)
            complete = total == inspected
            return PdfObservation(
                url=url,
                content_digest=digest,
                status="partial" if not complete else "observed" if candidates else "no_contact",
                reason="complete" if complete else "page_cap",
                pages_total=total,
                pages_inspected=inspected,
                complete_scan=complete,
                authors=authors,
                candidates=candidates,
                metadata=metadata,
                preferred_metadata=MetadataValues.model_validate(
                    {
                        field: next((m.value for m in metadata if m.field == field), None)
                        for field in ("title", "journal", "publication_date", "doi")
                    }
                ),
            )
    except Refusal as error:
        return refused(error.reason)
    except LimitReachedError:
        return refused("resource_limit")
    except DependencyError:
        return refused("encrypted" if b"/Encrypt" in data else "unsupported_font_or_structure")
    except (PyPdfError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        return refused("corrupt")
