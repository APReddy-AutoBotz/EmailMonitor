"""Bounded, fail-closed NISO JATS XML extraction for Open Access articles.

Extracts structured author identities, correspondence status, affiliations,
and literal email evidence with full cryptographic provenance.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal
from xml.parsers import expat

from pydantic import Field, model_validator

from emailmonitor.extraction.html import AuthorFact, CandidateFact, Evidence, Fact
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import (
    OpenAccessIdentifier,
    open_access_url,
)

MAX_BYTES = 4_194_304  # 4 MB
MAX_NODES = 40_000
MAX_DEPTH = 48
MAX_TEXT = 2_097_152

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
ORCID_PATTERN = re.compile(r"([0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X])")


class JatsObservation(Fact):
    parser_version: Literal["open-access-jats-v1"] = "open-access-jats-v1"
    route: Literal["jats_xml"] = "jats_xml"
    url: str = Field(max_length=2048)
    requested_identifier: OpenAccessIdentifier
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "partial", "unsupported"]
    title: str | None = Field(default=None, max_length=1000)
    journal: str | None = Field(default=None, max_length=1000)
    doi: str | None = Field(default=None, max_length=256)
    publication_date: str | None = Field(default=None, max_length=100)
    authors: list[AuthorFact] = Field(default_factory=list, max_length=100)
    candidates: list[CandidateFact] = Field(default_factory=list, max_length=100)
    identity_association_implemented: Literal[False] = False

    @model_validator(mode="after")
    def validate_jats_consistency(self) -> "JatsObservation":
        expected_url = open_access_url(self.requested_identifier)
        if self.url != expected_url:
            raise ValueError(f"URL mismatch: {self.url} vs {expected_url}")
        if self.authors:
            expected_positions = list(range(1, len(self.authors) + 1))
            actual_positions = [a.position for a in self.authors]
            if actual_positions != expected_positions:
                raise ValueError("Authors must be contiguously numbered starting at 1")
            for a in self.authors:
                if a.first != (a.position == 1):
                    raise ValueError(f"Author at position {a.position} has incorrect first flag")
        if self.status in ("observed", "no_contact"):
            if (self.status == "observed") != bool(self.candidates):
                raise ValueError(
                    "Status 'observed' requires candidates; 'no_contact' forbids candidates"
                )
        return self


@dataclass(eq=False)
class JatsNode:
    tag: str
    attrs: dict[str, str]
    locator: str
    parent: "JatsNode | None" = None
    children: list["JatsNode"] = field(default_factory=list)
    text_chunks: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts: list[str] = []
        for chunk in self.text_chunks:
            parts.append(chunk)
        for child in self.children:
            child_text = child.text()
            if child_text:
                parts.append(child_text)
        return " ".join("".join(parts).split())

    def own_text(self) -> str:
        return " ".join("".join(self.text_chunks).split())

    def find_all(self, tag: str) -> list["JatsNode"]:
        results: list[JatsNode] = []
        for child in self.children:
            if child.tag == tag:
                results.append(child)
            results.extend(child.find_all(tag))
        return results

    def find_first(self, tag: str) -> "JatsNode | None":
        for child in self.children:
            if child.tag == tag:
                return child
            found = child.find_first(tag)
            if found is not None:
                return found
        return None


def _clean_tag(name: str) -> str:
    # Strip namespace URI if present (e.g. {http://...}tag)
    if "}" in name:
        return name.split("}", 1)[1].lower()
    if ":" in name:
        return name.split(":", 1)[1].lower()
    return name.lower()


class _JatsBuilder:
    def __init__(self) -> None:
        self.node_count = 0
        self.total_text = 0
        self.root: JatsNode | None = None
        self.current: JatsNode | None = None
        self.child_counters: list[dict[str, int]] = [{}]

    def start_element(self, name: str, attrs: dict[str, str]) -> None:
        self.node_count += 1
        if self.node_count > MAX_NODES:
            raise FetchDenied("jats_xml_node_limit_exceeded")
        tag = _clean_tag(name)
        counters = self.child_counters[-1]
        counters[tag] = counters.get(tag, 0) + 1
        index = counters[tag]

        if self.current is None:
            locator = f"/{tag}[{index}]"
            node = JatsNode(tag=tag, attrs=attrs, locator=locator)
            self.root = node
            self.current = node
        else:
            depth = len(self.child_counters)
            if depth > MAX_DEPTH:
                raise FetchDenied("jats_xml_depth_limit_exceeded")
            locator = f"{self.current.locator}/{tag}[{index}]"
            node = JatsNode(tag=tag, attrs=attrs, locator=locator, parent=self.current)
            self.current.children.append(node)
            self.current = node

        self.child_counters.append({})

    def end_element(self, name: str) -> None:
        if self.current is not None:
            self.current = self.current.parent
        self.child_counters.pop()

    def char_data(self, data: str) -> None:
        if not data:
            return
        self.total_text += len(data)
        if self.total_text > MAX_TEXT:
            raise FetchDenied("jats_xml_text_limit_exceeded")
        if self.current is not None:
            self.current.text_chunks.append(data)


def parse_jats_xml(data: bytes, requested_identifier: OpenAccessIdentifier) -> JatsObservation:
    """Parse raw JATS XML bytes into a validated JatsObservation."""
    if len(data) > MAX_BYTES:
        raise FetchDenied("jats_xml_byte_limit_exceeded")
    if not data.strip():
        raise FetchDenied("empty_jats_xml_payload")

    content_digest = hashlib.sha256(data).hexdigest()
    builder = _JatsBuilder()

    # Create safe Expat parser without entity expansion or external resources
    parser = expat.ParserCreate(encoding="utf-8")
    parser.StartElementHandler = builder.start_element
    parser.EndElementHandler = builder.end_element
    parser.CharacterDataHandler = builder.char_data
    parser.buffer_text = True

    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise FetchDenied(f"malformed_jats_xml: {exc}") from exc

    root = builder.root
    if root is None:
        raise FetchDenied("missing_root_element")

    # Locate article metadata
    article_meta = root.find_first("article-meta")
    front = root.find_first("front")

    title: str | None = None
    journal: str | None = None
    doi: str | None = None
    pub_date: str | None = None

    if front:
        journal_title_node = front.find_first("journal-title")
        if journal_title_node:
            journal_text = journal_title_node.text()
            if journal_text:
                journal = journal_text[:1000]

    if article_meta:
        # Title
        title_node = article_meta.find_first("article-title")
        if title_node:
            t = title_node.text()
            if t:
                title = t[:1000]

        # DOI
        for id_node in article_meta.find_all("article-id"):
            pub_id_type = id_node.attrs.get("pub-id-type", "").lower()
            if pub_id_type == "doi":
                doi_val = id_node.text()
                if doi_val:
                    doi = doi_val[:256]
                break

        # Publication date
        pub_date_node = article_meta.find_first("pub-date")
        if pub_date_node:
            year_node = pub_date_node.find_first("year")
            month_node = pub_date_node.find_first("month")
            day_node = pub_date_node.find_first("day")
            if year_node and year_node.text():
                parts = [year_node.text()]
                if month_node and month_node.text():
                    parts.append(month_node.text().zfill(2))
                    if day_node and day_node.text():
                        parts.append(day_node.text().zfill(2))
                pub_date = "-".join(parts)[:100]

    # Map affiliations: aff_id -> list of affiliation text
    affiliations_by_id: dict[str, list[str]] = {}
    corresp_by_id: dict[str, list[tuple[str, str]]] = {}  # id -> list of (email, locator)

    if article_meta:
        for aff in article_meta.find_all("aff"):
            aff_id = aff.attrs.get("id")
            if aff_id:
                # Text of institution or whole affiliation
                aff_text = aff.text()
                # Clean label numbers if present at start
                label_node = aff.find_first("label")
                if label_node and aff_text.startswith(label_node.text()):
                    aff_text = aff_text[len(label_node.text()):].strip()
                if aff_text:
                    affiliations_by_id.setdefault(aff_id, []).append(aff_text[:1000])

        # Author notes and correspondence blocks
        author_notes = article_meta.find_first("author-notes")
        if author_notes:
            for corresp in author_notes.find_all("corresp"):
                corresp_id = corresp.attrs.get("id")
                # Look for email tags or email regex in text
                found_emails: list[tuple[str, str]] = []
                for email_node in corresp.find_all("email"):
                    raw_email = email_node.text().strip()
                    if EMAIL_PATTERN.match(raw_email):
                        found_emails.append((raw_email, email_node.locator))
                if not found_emails:
                    text_match = EMAIL_PATTERN.findall(corresp.text())
                    for em in text_match:
                        found_emails.append((em, corresp.locator))
                if corresp_id:
                    corresp_by_id[corresp_id] = found_emails
                else:
                    corresp_by_id.setdefault("__default__", []).extend(found_emails)

    # Extract Authors
    authors: list[AuthorFact] = []
    author_corresp_flags: list[bool] = []
    author_corresp_rids: list[list[str]] = []
    direct_author_emails: list[list[tuple[str, str]]] = []

    if article_meta:
        for contrib in article_meta.find_all("contrib"):
            contrib_type = contrib.attrs.get("contrib-type", "author").lower()
            if contrib_type != "author":
                continue

            position = len(authors) + 1
            display_name = ""
            author_kind: Literal["person", "group", "unknown"] = "unknown"

            name_node = contrib.find_first("name")
            collab_node = contrib.find_first("collab")
            string_name_node = contrib.find_first("string-name")

            if name_node:
                surname_node = name_node.find_first("surname")
                given_node = name_node.find_first("given-names")
                surname = surname_node.text() if surname_node else ""
                given = given_node.text() if given_node else ""
                display_name = f"{given} {surname}".strip()
                author_kind = "person"
            elif collab_node:
                display_name = collab_node.text().strip()
                author_kind = "group"
            elif string_name_node:
                display_name = string_name_node.text().strip()
                author_kind = "person"

            if not display_name:
                continue

            # ORCID
            orcid: str | None = None
            contrib_id_node = contrib.find_first("contrib-id")
            if contrib_id_node:
                cid_type = contrib_id_node.attrs.get("contrib-id-type", "").lower()
                if "orcid" in cid_type:
                    orcid_match = ORCID_PATTERN.search(contrib_id_node.text())
                    if orcid_match:
                        orcid = orcid_match.group(1)

            # Correspondence flags
            is_corresp = contrib.attrs.get("corresp", "").lower() == "yes"
            corresp_rids: list[str] = []
            for xref in contrib.find_all("xref"):
                if xref.attrs.get("ref-type", "").lower() == "corresp":
                    rid = xref.attrs.get("rid")
                    if rid:
                        corresp_rids.append(rid)
                        is_corresp = True

            # Direct emails inside contrib
            contrib_emails: list[tuple[str, str]] = []
            for em_node in contrib.find_all("email"):
                raw_em = em_node.text().strip()
                if EMAIL_PATTERN.match(raw_em):
                    contrib_emails.append((raw_em, em_node.locator))
                    is_corresp = True

            # Affiliations for this author
            aff_texts: list[str] = []
            for xref in contrib.find_all("xref"):
                if xref.attrs.get("ref-type", "").lower() == "aff":
                    rid = xref.attrs.get("rid")
                    if rid and rid in affiliations_by_id:
                        for text in affiliations_by_id[rid]:
                            if text not in aff_texts:
                                aff_texts.append(text)
            # Direct aff inside contrib
            for direct_aff in contrib.find_all("aff"):
                dt = direct_aff.text()
                if dt and dt not in aff_texts:
                    aff_texts.append(dt[:1000])

            author_evidence = [
                Evidence(
                    locator=contrib.locator,
                    excerpt=display_name[:300],
                    kind="structured_metadata",
                )
            ]

            authors.append(
                AuthorFact(
                    position=position,
                    display_name=display_name[:300],
                    affiliations=aff_texts[:20],
                    orcid=orcid,
                    author_kind=author_kind,
                    first=(position == 1),
                    corresponding=True if is_corresp else False,
                    evidence=author_evidence,
                )
            )
            author_corresp_flags.append(is_corresp)
            author_corresp_rids.append(corresp_rids)
            direct_author_emails.append(contrib_emails)

    # Candidates resolution
    candidates: list[CandidateFact] = []
    seen_addresses: set[str] = set()

    # 1. Direct emails inside contrib
    for pos_idx, email_list in enumerate(direct_author_emails):
        author_pos = pos_idx + 1
        for em, locator in email_list:
            if em in seen_addresses:
                continue
            seen_addresses.add(em)
            candidates.append(
                CandidateFact(
                    raw_address=em,
                    author_positions=[author_pos],
                    association_status="needs_review",
                    technical_status="not_checked",
                    delivery_status="unverified",
                    outreach_eligibility="not_assessed",
                    evidence=Evidence(
                        locator=locator,
                        excerpt=em[:300],
                        kind="structured_metadata",
                    ),
                )
            )

    # 2. Corresp referenced via rid
    for pos_idx, rids in enumerate(author_corresp_rids):
        author_pos = pos_idx + 1
        for rid in rids:
            if rid in corresp_by_id:
                for em, locator in corresp_by_id[rid]:
                    if em in seen_addresses:
                        continue
                    seen_addresses.add(em)
                    candidates.append(
                        CandidateFact(
                            raw_address=em,
                            author_positions=[author_pos],
                            association_status="needs_review",
                            technical_status="not_checked",
                            delivery_status="unverified",
                            outreach_eligibility="not_assessed",
                            evidence=Evidence(
                                locator=locator,
                                excerpt=em[:300],
                                kind="structured_metadata",
                            ),
                        )
                    )

    # 3. Default author notes emails if not yet associated
    corresp_authors = [i + 1 for i, flag in enumerate(author_corresp_flags) if flag]
    for _corresp_id, email_list in corresp_by_id.items():
        for em, locator in email_list:
            if em in seen_addresses:
                continue
            seen_addresses.add(em)
            # If exactly one corresponding author exists in the article, associate!
            if len(corresp_authors) == 1:
                assigned_positions = [corresp_authors[0]]
                status: Literal["needs_review", "unmatched"] = "needs_review"
            else:
                assigned_positions = []
                status = "unmatched"

            candidates.append(
                CandidateFact(
                    raw_address=em,
                    author_positions=assigned_positions,
                    association_status=status,
                    technical_status="not_checked",
                    delivery_status="unverified",
                    outreach_eligibility="not_assessed",
                    evidence=Evidence(
                        locator=locator,
                        excerpt=em[:300],
                        kind="structured_metadata",
                    ),
                )
            )

    status_val: Literal["observed", "no_contact", "unsupported"] = (
        "observed" if candidates else ("no_contact" if authors else "unsupported")
    )

    return JatsObservation(
        url=open_access_url(requested_identifier),
        requested_identifier=requested_identifier,
        content_digest=content_digest,
        status=status_val,
        title=title,
        journal=journal,
        doi=doi,
        publication_date=pub_date,
        authors=authors,
        candidates=candidates,
    )
