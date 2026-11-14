"""Publisher landing-page extraction from supplied HTML bytes (Highwire/DC/PRISM).

Most Open Access publishers expose machine-readable bibliographic ``<meta>``
tags (the Highwire Press ``citation_*`` convention used by Google Scholar),
and many print a "Correspondence" block with ``mailto:`` links. This module
turns **already supplied** page bytes into observations:

* Highwire ``citation_author`` starts an author; following
  ``citation_author_institution``/``_email``/``_orcid`` tags belong to that
  author (the documented Highwire ordering). That ordering is the association
  basis ``highwire_author_sequence``.
* A ``mailto:`` link is a candidate only when its enclosing block reads as a
  correspondence statement and it is not inside header/footer/nav/aside/form
  chrome. It is linked to an author only by an exact surname in that block.

Never done here: network access, following ``citation_pdf_url``, script or
style evaluation, decoding of anti-scraping obfuscation (e.g. Cloudflare
``data-cfemail``; such addresses are only *counted* for manual review), or
completing partial addresses. Page text is untrusted data.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.extraction.jats import clean_address
from emailmonitor.fetching.safety import FetchDenied

PARSER_VERSION: Literal["citation-meta-v1"] = "citation-meta-v1"
MAX_BYTES = 5_242_880
MAX_META = 4_000
MAX_NODES = 60_000
MAX_DEPTH = 256
MAX_AUTHORS = 100
MAX_CANDIDATES = 100

_INERT = frozenset({"script", "style", "template", "noscript", "svg", "iframe", "object"})
_CHROME = frozenset({"header", "footer", "nav", "aside", "form", "button", "select"})
_CHROME_HINT = re.compile(
    r"(^|[\s_-])(footer|header|nav|navbar|menu|sidebar|cookie|newsletter|subscribe|"
    r"advert|ads?|social|share|breadcrumb)([\s_-]|$)",
    re.IGNORECASE,
)
_BLOCK = frozenset(
    {"p", "div", "li", "section", "article", "td", "dd", "dt", "span", "address", "sup", "small"}
)
_VOID = frozenset(
    {"meta", "link", "img", "br", "hr", "input", "source", "wbr", "area", "base", "col", "embed"}
)
_CORRESPONDENCE = re.compile(
    r"\b(correspond(?:ence|ing)(?:\s+author)?s?|e-?mail\s*:|address\s+correspondence|"
    r"contact\s+author)\b",
    re.IGNORECASE,
)
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")

CandidateBasis = Literal[
    "highwire_author_sequence",
    "correspondence_block_surname",
    "unmatched",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PageEvidence(Contract):
    locator: str = Field(min_length=1, max_length=512)
    excerpt: str = Field(max_length=300)
    kind: Literal["citation_meta", "correspondence_mailto"]


class PageAuthor(Contract):
    position: int = Field(ge=1, le=MAX_AUTHORS)
    display_name: str = Field(min_length=1, max_length=300)
    institutions: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
    first: bool
    # Highwire has no standard correspondence tag; True only from an explicit
    # correspondence block naming the author or a citation_author_email.
    corresponding: bool | None
    evidence: PageEvidence


class PageCandidate(Contract):
    raw_address: str = Field(min_length=3, max_length=320)
    author_positions: tuple[int, ...] = Field(default_factory=tuple, max_length=1)
    association_basis: CandidateBasis
    association_status: Literal["needs_review", "unmatched"]
    evidence: PageEvidence

    @model_validator(mode="after")
    def consistent(self) -> PageCandidate:
        unmatched = self.association_basis == "unmatched"
        if unmatched == bool(self.author_positions) or unmatched != (
            self.association_status == "unmatched"
        ):
            raise ValueError("association basis, positions and status disagree")
        return self


class PageObservation(Contract):
    parser_version: Literal["citation-meta-v1"] = PARSER_VERSION
    page_url: str | None = Field(default=None, max_length=2048)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "unsupported"]
    title: str | None = Field(default=None, max_length=1000)
    journal: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=500)
    doi: str | None = Field(default=None, max_length=256)
    publication_date: str | None = Field(default=None, max_length=32)
    pdf_url: str | None = Field(default=None, max_length=2048)
    keywords: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    authors: tuple[PageAuthor, ...] = Field(default_factory=tuple, max_length=MAX_AUTHORS)
    candidates: tuple[PageCandidate, ...] = Field(default_factory=tuple, max_length=MAX_CANDIDATES)
    obfuscated_address_count: int = Field(default=0, ge=0)
    metadata_tag_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent(self) -> PageObservation:
        if [a.position for a in self.authors] != list(range(1, len(self.authors) + 1)):
            raise ValueError("authors must be contiguous from 1")
        known = {a.position for a in self.authors}
        if any(p not in known for c in self.candidates for p in c.author_positions):
            raise ValueError("candidate references an unknown author")
        if (self.status == "observed") != bool(self.candidates):
            raise ValueError("status disagrees with candidates")
        return self


@dataclass(eq=False)
class _Node:
    tag: str
    attrs: dict[str, str]
    index: int
    parent: _Node | None
    content: list[str | _Node] = field(default_factory=list)

    def chrome(self) -> bool:
        node: _Node | None = self
        while node is not None:
            if node.tag in _CHROME or node.tag in _INERT:
                return True
            hint = f"{node.attrs.get('class', '')} {node.attrs.get('id', '')} " + (
                node.attrs.get("role", "")
            )
            if _CHROME_HINT.search(hint) or node.attrs.get("role") in (
                "navigation",
                "banner",
                "contentinfo",
            ):
                return True
            if "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true":
                return True
            node = node.parent
        return False

    def text(self) -> str:
        parts: list[str] = []
        for item in self.content:
            if isinstance(item, str):
                parts.append(item)
            elif item.tag not in _INERT:
                parts.append(" " + item.text() + " ")
        return " ".join("".join(parts).split())

    def block(self) -> _Node:
        node: _Node = self
        while node.parent is not None and (node.tag not in _BLOCK or node.tag == "span"):
            node = node.parent
        return node


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, 0, None)
        self.current = self.root
        self.depth = 0
        self.nodes = 0
        self.meta: list[tuple[int, str, str]] = []  # (index, name, content)
        self.mailto: list[tuple[int, _Node, str]] = []  # (index, anchor, href)
        self.obfuscated = 0
        self.inert_depth = 0

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Node:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FetchDenied("html_node_limit_exceeded")
        values = {k.lower(): (v or "") for k, v in attrs[:64]}
        return _Node(tag, values, self.nodes, self.current)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = self._open(tag, attrs)
        if tag == "meta":
            name = (node.attrs.get("name") or node.attrs.get("property") or "").strip().lower()
            content = node.attrs.get("content", "")
            if name and content and len(self.meta) < MAX_META:
                self.meta.append((node.index, name[:100], " ".join(content.split())[:2000]))
        if (
            "data-cfemail" in node.attrs
            or "__cf_email__" in node.attrs.get("class", "")
            or "/cdn-cgi/l/email-protection" in node.attrs.get("href", "")
        ):
            self.obfuscated += 1  # counted once per element; never decoded
        if self.inert_depth == 0:
            self.current.content.append(node)
        if tag == "a":
            href = node.attrs.get("href", "").strip()
            if href.lower().startswith("mailto:") and self.inert_depth == 0:
                self.mailto.append((node.index, node, href))
        if tag in _VOID:
            return
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FetchDenied("html_depth_limit_exceeded")
        if tag in _INERT:
            self.inert_depth += 1
        self.current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _VOID or tag == "meta":
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _VOID:
            return
        node: _Node | None = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is None or node.parent is None:
            return  # stray end tag
        while self.current is not node:
            if self.current.tag in _INERT:
                self.inert_depth -= 1
            self.current = self.current.parent or self.root
            self.depth -= 1
        if node.tag in _INERT:
            self.inert_depth -= 1
        self.current = node.parent or self.root
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.inert_depth == 0 and data:
            self.current.content.append(data)


def _surname(name: str) -> str:
    tokens = [t for t in re.split(r"[\s,]+", name) if t]
    if not tokens:
        return ""
    # Highwire often writes "Surname, Given"; otherwise the last token.
    return tokens[0] if "," in name else tokens[-1]


def _display(name: str) -> str:
    if "," in name:
        surname, _, given = name.partition(",")
        if given.strip():
            return f"{given.strip()} {surname.strip()}"
    return " ".join(name.split())


def normalize_page_date(value: str) -> str | None:
    """ISO-shape a Highwire/DC date (YYYY[/-]MM[/-]DD, YYYY[/-]MM or YYYY); else None."""
    match = re.fullmatch(r"\s*((?:19|20)\d\d)(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?\s*", value)
    if not match:
        match = re.match(r"\s*((?:19|20)\d\d)-(\d{2})-(\d{2})T", value)
        if not match:
            return None
    year, month, day = match.group(1), match.group(2), match.group(3)
    if month is None:
        return year
    if not 1 <= int(month) <= 12:
        return None
    if day is None:
        return f"{year}-{int(month):02d}"
    if not 1 <= int(day) <= 31:
        return None
    return f"{year}-{int(month):02d}-{int(day):02d}"


def parse_citation_page(data: bytes, page_url: str | None = None) -> PageObservation:
    """Parse supplied landing-page bytes into structured contact observations."""
    if len(data) > MAX_BYTES:
        raise FetchDenied("html_byte_limit_exceeded")
    if not data.strip():
        raise FetchDenied("empty_html_payload")
    if page_url is not None and (
        len(page_url) > 2048
        or not page_url.startswith("https://")
        or any(ord(c) <= 32 or ord(c) == 127 for c in page_url)
    ):
        raise FetchDenied("page_url_shape_denied")
    digest = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8", errors="replace")
    collector = _Collector()
    try:
        collector.feed(text)
        collector.close()
    except (AssertionError, ValueError) as exc:
        raise FetchDenied("malformed_html") from exc

    def first(*names: str) -> tuple[int, str] | None:
        for name in names:
            for index, meta_name, content in collector.meta:
                if meta_name == name and content:
                    return index, content
        return None

    title = first("citation_title", "dc.title", "og:title")
    journal = first("citation_journal_title", "prism.publicationname", "citation_conference_title")
    publisher = first("citation_publisher", "dc.publisher")
    pub_date = first(
        "citation_publication_date", "citation_online_date", "citation_date", "dc.date"
    )
    pdf = first("citation_pdf_url")
    doi_raw = first("citation_doi", "prism.doi", "dc.identifier", "bepress_citation_doi")
    doi: str | None = None
    if doi_raw:
        match = _DOI.search(doi_raw[1])
        if match:
            doi = match.group(1).rstrip(".").lower()
    keywords: list[str] = []
    for _index, name, content in collector.meta:
        if name in ("citation_keywords", "keywords", "dc.subject"):
            for word in re.split(r"[;,]", content):
                word = word.strip()
                if word and word not in keywords and len(keywords) < 50:
                    keywords.append(word[:200])

    # Highwire author sequence.
    authors: list[dict[str, object]] = []
    candidates: list[PageCandidate] = []
    seen: set[str] = set()
    pending_unmatched: list[tuple[int, str]] = []

    def add_candidate(
        address: str, positions: tuple[int, ...], basis: CandidateBasis, evidence: PageEvidence
    ) -> None:
        key = address.casefold()
        if key in seen or len(candidates) >= MAX_CANDIDATES:
            return
        seen.add(key)
        candidates.append(
            PageCandidate(
                raw_address=address,
                author_positions=positions,
                association_basis=basis,
                association_status="unmatched" if basis == "unmatched" else "needs_review",
                evidence=evidence,
            )
        )

    for index, name, content in collector.meta:
        if name in ("citation_author", "dc.creator") and len(authors) < MAX_AUTHORS:
            if name == "dc.creator" and any(a["source"] == "citation_author" for a in authors):
                continue
            authors.append(
                {
                    "name": _display(content)[:300],
                    "raw": content,
                    "index": index,
                    "source": name,
                    "institutions": [],
                    "orcid": None,
                    "corresponding": False,
                }
            )
        elif name == "citation_author_institution" and authors:
            institutions = authors[-1]["institutions"]
            assert isinstance(institutions, list)
            if content not in institutions and len(institutions) < 20:
                institutions.append(content[:1000])
        elif name == "citation_author_orcid" and authors:
            match = _ORCID.search(content)
            if match:
                authors[-1]["orcid"] = match.group(1)
        elif name == "citation_author_email":
            address = clean_address(content)
            if not address:
                continue
            if authors:
                authors[-1]["corresponding"] = True
                add_candidate(
                    address,
                    (len(authors),),
                    "highwire_author_sequence",
                    PageEvidence(
                        locator=f"meta[{index}][name=citation_author_email]",
                        excerpt=f"citation_author={authors[-1]['raw']}; "
                        f"citation_author_email={address}"[:300],
                        kind="citation_meta",
                    ),
                )
            else:
                pending_unmatched.append((index, address))

    for index, address in pending_unmatched:
        add_candidate(
            address,
            (),
            "unmatched",
            PageEvidence(
                locator=f"meta[{index}][name=citation_author_email]",
                excerpt=f"citation_author_email={address}",
                kind="citation_meta",
            ),
        )

    # Correspondence-block mailto links in article content.
    for index, anchor, href in collector.mailto:
        if anchor.chrome():
            continue
        address = clean_address(href.split("?", 1)[0])
        if not address:
            continue
        block = anchor.block()
        block_text = block.text()
        if not _CORRESPONDENCE.search(block_text):
            continue
        hits = [
            pos
            for pos, author in enumerate(authors, start=1)
            if len(_surname(str(author["raw"]))) >= 2
            and re.search(
                rf"(?<!\w){re.escape(_surname(str(author['raw'])))}(?!\w)",
                block_text,
                re.IGNORECASE,
            )
        ]
        evidence = PageEvidence(
            locator=f"a[{index}][href^=mailto]",
            excerpt=block_text[:300],
            kind="correspondence_mailto",
        )
        if len(hits) == 1:
            authors[hits[0] - 1]["corresponding"] = True
            add_candidate(address, (hits[0],), "correspondence_block_surname", evidence)
        else:
            add_candidate(address, (), "unmatched", evidence)

    any_corresp = any(bool(a["corresponding"]) for a in authors)
    page_authors = tuple(
        PageAuthor(
            position=pos,
            display_name=str(a["name"]) or "Unknown",
            institutions=tuple(a["institutions"]) if isinstance(a["institutions"], list) else (),
            orcid=a["orcid"] if isinstance(a["orcid"], str) else None,
            first=pos == 1,
            corresponding=True if a["corresponding"] else (False if any_corresp else None),
            evidence=PageEvidence(
                locator=f"meta[{a['index']}][name={a['source']}]",
                excerpt=str(a["raw"])[:300],
                kind="citation_meta",
            ),
        )
        for pos, a in enumerate(authors, start=1)
    )
    has_metadata = bool(collector.meta) and (title is not None or page_authors)
    status: Literal["observed", "no_contact", "unsupported"] = (
        "observed" if candidates else ("no_contact" if has_metadata else "unsupported")
    )
    return PageObservation(
        page_url=page_url,
        content_digest=digest,
        status=status,
        title=title[1][:1000] if title else None,
        journal=journal[1][:1000] if journal else None,
        publisher=publisher[1][:500] if publisher else None,
        doi=doi,
        publication_date=normalize_page_date(pub_date[1]) if pub_date else None,
        pdf_url=pdf[1][:2048] if pdf and pdf[1].startswith("https://") else None,
        keywords=tuple(keywords),
        authors=page_authors,
        candidates=tuple(candidates),
        obfuscated_address_count=collector.obfuscated,
        metadata_tag_count=len(collector.meta),
    )
