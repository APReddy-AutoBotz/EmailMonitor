"""Bounded, fail-closed NISO JATS XML extraction for Open Access articles.

Extracts structured author identities, correspondence status, affiliations,
and literal email evidence with full cryptographic provenance.

Rules that keep observations truthful:

* An address is only ever copied from the document (``<email>``, an email
  ``<ext-link>``/``<uri>``, or literal text inside a correspondence note). It
  is never constructed, completed or guessed.
* A ``<contrib>`` holding an ``<email>`` is *not* thereby a corresponding
  author; only ``corresp="yes"`` or a cross-reference to a correspondence note
  asserts that role. When an article declares no correspondence at all the
  role stays unknown (``None``).
* Every candidate records the structural basis of its author link. Shared
  correspondence notes are split only by an explicit initials parenthetical or
  an unambiguous surname directly preceding the address; otherwise the address
  stays unmatched for operator review.
* DTD internal subsets and entity declarations are refused before expansion.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal
from xml.parsers import expat

from pydantic import Field, model_validator

from emailmonitor.extraction.attribution import (
    Person,
    attribute_spans,
    clean_address,
    find_addresses,
)
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
MAX_KEYWORDS = 50
MAX_NOTE_ADDRESSES = 200
__all__ = ["clean_address", "find_addresses", "parse_jats_xml"]

ORCID_PATTERN = re.compile(r"([0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X])")
_CORRESP_FN_TYPES = frozenset({"corresp", "correspondence", "corresponding-author"})
_PUB_DATE_PREFERENCE = ("epub", "pub", "ppub", "collection", "epub-ppub")

AssociationBasis = Literal[
    "contrib_email",
    "corresp_xref",
    "corresp_initials",
    "corresp_name_proximity",
    "sole_corresponding_author",
    "unmatched",
]


class JatsCandidateFact(CandidateFact):
    """A literal address plus the structural reason (if any) it maps to an author."""

    association_basis: AssociationBasis

    @model_validator(mode="after")
    def basis_matches_positions(self) -> "JatsCandidateFact":
        unmatched = self.association_basis == "unmatched"
        if unmatched != (not self.author_positions):
            raise ValueError("association basis must agree with author positions")
        if unmatched != (self.association_status == "unmatched"):
            raise ValueError("association basis must agree with association status")
        return self


class JatsObservation(Fact):
    parser_version: Literal["open-access-jats-v2"] = "open-access-jats-v2"
    route: Literal["jats_xml"] = "jats_xml"
    url: str = Field(max_length=2048)
    requested_identifier: OpenAccessIdentifier
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "partial", "unsupported"]
    title: str | None = Field(default=None, max_length=1000)
    journal: str | None = Field(default=None, max_length=1000)
    doi: str | None = Field(default=None, max_length=256)
    article_pmcid: str | None = Field(default=None, pattern=r"^PMC\d{1,12}$")
    publication_date: str | None = Field(default=None, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=MAX_KEYWORDS)
    license_url: str | None = Field(default=None, max_length=2048)
    authors: list[AuthorFact] = Field(default_factory=list, max_length=100)
    candidates: list[JatsCandidateFact] = Field(default_factory=list, max_length=100)
    authors_truncated: bool = False
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
        known_positions = {a.position for a in self.authors}
        for c in self.candidates:
            if any(p not in known_positions for p in c.author_positions):
                raise ValueError("Candidate references an unknown author position")
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
    content: list["str | JatsNode"] = field(default_factory=list)
    order: int = 0  # document order; locators sort lexicographically, not by position

    def text(self, skip: frozenset[str] = frozenset()) -> str:
        """Document-order text; element boundaries become word boundaries."""
        parts: list[str] = []
        for item in self.content:
            if isinstance(item, str):
                parts.append(item)
            elif item.tag not in skip:
                parts.append(" " + item.text(skip) + " ")
        joined = " ".join("".join(parts).split())
        joined = re.sub(r"\s+([,.;:)\]])", r"\1", joined)
        return re.sub(r"([(\[])\s+", r"\1", joined)

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

    def has_ancestor(self, tag: str, stop: "JatsNode | None" = None) -> bool:
        node = self.parent
        while node is not None and node is not stop:
            if node.tag == tag:
                return True
            node = node.parent
        return False


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
            node = JatsNode(tag=tag, attrs=attrs, locator=locator, order=self.node_count)
            self.root = node
            self.current = node
        else:
            depth = len(self.child_counters)
            if depth > MAX_DEPTH:
                raise FetchDenied("jats_xml_depth_limit_exceeded")
            locator = f"{self.current.locator}/{tag}[{index}]"
            node = JatsNode(
                tag=tag, attrs=attrs, locator=locator, parent=self.current, order=self.node_count
            )
            self.current.children.append(node)
            self.current.content.append(node)
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
            self.current.content.append(data)


def _deny_doctype(
    doctype_name: str, system_id: str | None, public_id: str | None, has_internal_subset: int
) -> None:
    if has_internal_subset:
        raise FetchDenied("jats_internal_dtd_subset_denied")


def _deny_entity(*_args: object) -> None:
    raise FetchDenied("jats_entity_declaration_denied")


@dataclass(frozen=True)
class _Address:
    address: str
    locator: str
    excerpt: str
    offset: int  # position within the owning note's text, -1 when unknown


@dataclass
class _Note:
    note_id: str | None
    locator: str
    text: str
    addresses: list[_Address]


def _excerpt(text: str, start: int, length: int) -> str:
    if start < 0:
        return text[:300]
    lo = max(0, start - 160)
    hi = min(len(text), start + length + 80)
    return text[lo:hi][:300]


def _structured_addresses(node: JatsNode, own_only: bool = False) -> list[tuple[str, str]]:
    """(address, locator) for <email>, email <ext-link> and mailto <uri> descendants.

    ``own_only`` skips addresses inside nested ``<contrib>`` elements (group
    members), which belong to the member, not to the enclosing group author.
    """
    found: list[tuple[int, str, str]] = []

    def keep(child: JatsNode) -> bool:
        return not (own_only and child.has_ancestor("contrib", stop=node))

    for email_node in node.find_all("email"):
        if not keep(email_node):
            continue
        address = clean_address(email_node.text())
        if address:
            found.append((email_node.order, address, email_node.locator))
    for tag in ("ext-link", "uri"):
        for link in node.find_all(tag):
            if not keep(link):
                continue
            href = link.attrs.get("xlink:href") or link.attrs.get("href") or ""
            link_type = link.attrs.get("ext-link-type", "").lower()
            if link_type == "email" or href.lower().startswith("mailto:"):
                address = clean_address(href) if href else None
                address = address or clean_address(link.text())
                if address:
                    found.append((link.order, address, link.locator))
    found.sort()
    return [(address, locator) for _order, address, locator in found]


def _note_addresses(node: JatsNode) -> list[_Address]:
    text = node.text(skip=frozenset({"label"}))
    structured = _structured_addresses(node)
    result: list[_Address] = []
    visible = find_addresses(text)
    if structured:
        # Map structured addresses onto visible occurrences in order, linearly.
        positions: dict[str, list[int]] = {}
        for start, literal in visible:
            positions.setdefault(literal, []).append(start)
        last = -1
        for address, locator in structured[:MAX_NOTE_ADDRESSES]:
            queue = positions.get(address, [])
            while queue and queue[0] <= last:
                queue.pop(0)
            offset = queue.pop(0) if queue else -1
            if offset >= 0:
                last = offset
            result.append(_Address(address, locator, _excerpt(text, offset, len(address)), offset))
        return result
    for start, literal in visible[:MAX_NOTE_ADDRESSES]:
        result.append(_Address(literal, node.locator, _excerpt(text, start, len(literal)), start))
    return result


def _publication_date(article_meta: JatsNode) -> str | None:
    dates = article_meta.find_all("pub-date")
    if not dates:
        return None

    def rank(node: JatsNode) -> int:
        kind = (node.attrs.get("pub-type") or node.attrs.get("date-type") or "").lower()
        return _PUB_DATE_PREFERENCE.index(kind) if kind in _PUB_DATE_PREFERENCE else 99

    for node in sorted(dates, key=rank):
        year_node = node.find_first("year")
        if not year_node or not re.fullmatch(r"\d{4}", year_node.text()):
            continue
        parts = [year_node.text()]
        month_node = node.find_first("month")
        if month_node and re.fullmatch(r"\d{1,2}", month_node.text()):
            parts.append(month_node.text().zfill(2))
            day_node = node.find_first("day")
            if day_node and re.fullmatch(r"\d{1,2}", day_node.text()):
                parts.append(day_node.text().zfill(2))
        return "-".join(parts)
    return None


def _person_name(contrib: JatsNode) -> tuple[str, Literal["person", "group", "unknown"]]:
    direct = {child.tag: child for child in reversed(contrib.children)}
    name_node = direct.get("name")
    if name_node is None and "name-alternatives" in direct:
        name_node = direct["name-alternatives"].find_first("name")
    if name_node:
        surname_node = name_node.find_first("surname")
        given_node = name_node.find_first("given-names")
        surname = surname_node.text() if surname_node else ""
        given = given_node.text() if given_node else ""
        return f"{given} {surname}".strip(), "person"
    collab_node = direct.get("collab")
    if collab_node:
        return collab_node.text(skip=frozenset({"contrib-group"})).strip(), "group"
    string_name_node = direct.get("string-name")
    if string_name_node:
        return string_name_node.text().strip(), "person"
    return "", "unknown"


def parse_jats_xml(data: bytes, requested_identifier: OpenAccessIdentifier) -> JatsObservation:
    """Parse raw JATS XML bytes into a validated JatsObservation."""
    if len(data) > MAX_BYTES:
        raise FetchDenied("jats_xml_byte_limit_exceeded")
    if not data.strip():
        raise FetchDenied("empty_jats_xml_payload")

    content_digest = hashlib.sha256(data).hexdigest()
    builder = _JatsBuilder()

    # Safe Expat parser: no internal subset, no entity declarations, no external
    # parameter entities. External DTDs are never fetched.
    parser = expat.ParserCreate(encoding="utf-8")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _deny_doctype
    parser.EntityDeclHandler = _deny_entity
    parser.UnparsedEntityDeclHandler = _deny_entity
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

    article_meta = root.find_first("article-meta")
    front = root.find_first("front")

    title: str | None = None
    journal: str | None = None
    doi: str | None = None
    article_pmcid: str | None = None
    pub_date: str | None = None
    keywords: list[str] = []
    license_url: str | None = None

    if front:
        journal_title_node = front.find_first("journal-title")
        if journal_title_node:
            journal_text = journal_title_node.text()
            if journal_text:
                journal = journal_text[:1000]

    if article_meta:
        title_node = article_meta.find_first("article-title")
        if title_node:
            t = title_node.text()
            if t:
                title = t[:1000]

        for id_node in article_meta.find_all("article-id"):
            pub_id_type = id_node.attrs.get("pub-id-type", "").lower()
            value = id_node.text().strip()
            if pub_id_type == "doi" and value and doi is None:
                doi = value[:256]
            elif pub_id_type in ("pmc", "pmcid") and value and article_pmcid is None:
                digits = value.upper().removeprefix("PMC")
                if digits.isdigit() and 1 <= len(digits) <= 12:
                    article_pmcid = f"PMC{digits}"

        pub_date = _publication_date(article_meta)

        for kwd in article_meta.find_all("kwd"):
            word = kwd.text()
            if word and word not in keywords and len(keywords) < MAX_KEYWORDS:
                keywords.append(word[:200])

        license_node = article_meta.find_first("license")
        if license_node:
            href = license_node.attrs.get("xlink:href", "").strip()
            if href.startswith(("https://", "http://")):
                license_url = href[:2048]
            else:
                ali = license_node.find_first("license_ref")
                if ali and ali.text().startswith(("https://", "http://")):
                    license_url = ali.text()[:2048]

    affiliations_by_id: dict[str, list[str]] = {}
    notes: list[_Note] = []
    notes_by_id: dict[str, _Note] = {}

    if article_meta:
        for aff in article_meta.find_all("aff"):
            aff_id = aff.attrs.get("id")
            if aff_id:
                aff_text = aff.text(skip=frozenset({"label", "sup"}))
                if aff_text:
                    affiliations_by_id.setdefault(aff_id, []).append(aff_text[:1000])

        note_nodes = list(article_meta.find_all("corresp"))
        author_notes = article_meta.find_first("author-notes")
        if author_notes:
            for fn in author_notes.find_all("fn"):
                if fn.attrs.get("fn-type", "").lower() in _CORRESP_FN_TYPES:
                    note_nodes.append(fn)
        note_nodes.sort(key=lambda n: n.order)
        for node in note_nodes:
            note = _Note(
                note_id=node.attrs.get("id"),
                locator=node.locator,
                text=node.text(skip=frozenset({"label"})),
                addresses=_note_addresses(node),
            )
            notes.append(note)
            if note.note_id:
                notes_by_id[note.note_id] = note

    authors: list[AuthorFact] = []
    authors_truncated = False
    author_signals: list[bool] = []
    author_note_refs: list[list[str]] = []
    direct_author_emails: list[list[tuple[str, str]]] = []

    if article_meta:
        for contrib in article_meta.find_all("contrib"):
            contrib_type = contrib.attrs.get("contrib-type", "author").lower()
            if contrib_type != "author":
                continue
            if contrib.has_ancestor("contrib", stop=article_meta):
                continue  # members of a group author; the group holds the position

            display_name, author_kind = _person_name(contrib)
            if not display_name:
                continue
            if len(authors) >= 100:
                authors_truncated = True
                continue
            position = len(authors) + 1

            orcid: str | None = None
            for contrib_id_node in contrib.find_all("contrib-id"):
                cid_type = contrib_id_node.attrs.get("contrib-id-type", "").lower()
                if "orcid" in cid_type:
                    orcid_match = ORCID_PATTERN.search(contrib_id_node.text())
                    if orcid_match:
                        orcid = orcid_match.group(1)
                        break

            signal = contrib.attrs.get("corresp", "").lower() == "yes"
            refs: list[str] = []
            for xref in contrib.find_all("xref"):
                ref_type = xref.attrs.get("ref-type", "").lower()
                rid_attr = xref.attrs.get("rid", "")
                for rid in rid_attr.split():
                    if ref_type == "corresp" or (
                        ref_type in ("fn", "author-notes") and rid in notes_by_id
                    ):
                        refs.append(rid)
                        signal = True

            contrib_emails = _structured_addresses(contrib, own_only=True)

            aff_texts: list[str] = []
            for xref in contrib.find_all("xref"):
                if xref.attrs.get("ref-type", "").lower() == "aff":
                    for rid in xref.attrs.get("rid", "").split():
                        for text in affiliations_by_id.get(rid, []):
                            if text not in aff_texts:
                                aff_texts.append(text)
            for direct_aff in contrib.find_all("aff"):
                dt = direct_aff.text(skip=frozenset({"label", "sup"}))
                if dt and dt[:1000] not in aff_texts:
                    aff_texts.append(dt[:1000])

            authors.append(
                AuthorFact(
                    position=position,
                    display_name=display_name[:300],
                    affiliations=aff_texts[:20],
                    orcid=orcid,
                    author_kind=author_kind,
                    first=(position == 1),
                    corresponding=signal,
                    evidence=[
                        Evidence(
                            locator=contrib.locator,
                            excerpt=display_name[:300],
                            kind="structured_metadata",
                        )
                    ],
                )
            )
            author_signals.append(signal)
            author_note_refs.append(refs)
            direct_author_emails.append(contrib_emails)

    # Role is unknown (None) when the article declares no correspondence at all.
    if authors and not any(author_signals) and not notes:
        authors = [a.model_copy(update={"corresponding": None}) for a in authors]

    candidates: list[JatsCandidateFact] = []
    seen: set[str] = set()

    def add(
        address: str,
        locator: str,
        excerpt: str,
        positions: list[int],
        basis: AssociationBasis,
    ) -> None:
        key = address.casefold()
        if key in seen or len(candidates) >= 100:
            return
        seen.add(key)
        candidates.append(
            JatsCandidateFact(
                raw_address=address,
                author_positions=positions,
                association_status="unmatched" if basis == "unmatched" else "needs_review",
                technical_status="not_checked",
                delivery_status="unverified",
                outreach_eligibility="not_assessed",
                association_basis=basis,
                evidence=Evidence(
                    locator=locator, excerpt=excerpt[:300], kind="structured_metadata"
                ),
            )
        )

    # 1. Addresses inside an author's own <contrib>.
    for pos_idx, email_list in enumerate(direct_author_emails):
        for address, locator in email_list:
            add(address, locator, address, [pos_idx + 1], "contrib_email")

    # 2. Correspondence notes: referenced ones first, then unreferenced ones.
    referencing: dict[str, list[int]] = {}
    for pos_idx, refs in enumerate(author_note_refs):
        for rid in refs:
            referencing.setdefault(rid, [])
            if pos_idx + 1 not in referencing[rid]:
                referencing[rid].append(pos_idx + 1)
    corresponding_positions = [a.position for a in authors if a.corresponding]
    people = [Person(a.position, a.display_name) for a in authors if a.author_kind == "person"]

    for referenced_pass in (True, False):
        for note in notes:
            refs_for_note = referencing.get(note.note_id or "", [])
            if bool(refs_for_note) != referenced_pass:
                continue
            single = len(note.addresses) == 1
            located = [e for e in note.addresses if e.offset >= 0]
            owners = dict(
                zip(
                    (id(e) for e in located),
                    attribute_spans(
                        note.text,
                        [(e.offset, e.offset + len(e.address)) for e in located],
                        people,
                    ),
                    strict=True,
                )
            )
            for entry in note.addresses:
                if len(candidates) >= 100:
                    break
                owner, kind = owners.get(id(entry), (None, None))
                # A sole address may inherit the note's structural owner unless an
                # explicit label names somebody else.
                structural: tuple[int, AssociationBasis] | None = None
                if single and len(refs_for_note) == 1:
                    structural = (refs_for_note[0], "corresp_xref")
                elif single and not refs_for_note and len(corresponding_positions) == 1:
                    structural = (corresponding_positions[0], "sole_corresponding_author")
                if structural and (owner is None or owner == structural[0]):
                    add(entry.address, entry.locator, entry.excerpt, [structural[0]], structural[1])
                elif owner is not None and kind is not None and not structural:
                    basis: AssociationBasis = (
                        "corresp_initials" if kind == "initials" else "corresp_name_proximity"
                    )
                    add(entry.address, entry.locator, entry.excerpt, [owner], basis)
                else:
                    add(entry.address, entry.locator, entry.excerpt, [], "unmatched")

    # A note that names its author asserts correspondence even without an xref.
    # Without any explicit author marker, unpicked authors stay unknown (None).
    note_picked = {
        p
        for c in candidates
        if c.association_basis
        in (
            "corresp_xref",
            "corresp_initials",
            "corresp_name_proximity",
            "sole_corresponding_author",
        )
        for p in c.author_positions
    }
    if authors and not any(author_signals) and notes:
        authors = [
            a.model_copy(update={"corresponding": True if a.position in note_picked else None})
            for a in authors
        ]
    elif note_picked:
        authors = [
            a.model_copy(update={"corresponding": True}) if a.position in note_picked else a
            for a in authors
        ]

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
        article_pmcid=article_pmcid,
        publication_date=pub_date,
        keywords=keywords,
        license_url=license_url,
        authors=authors,
        candidates=candidates,
        authors_truncated=authors_truncated,
    )
