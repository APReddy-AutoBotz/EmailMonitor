"""Inert, bounded Elsevier XML observations. No transport or identity acceptance.

Only the declared journal-head profile is supported. Parsing bytes does not grant
source rights, bind a tenant, or establish OS/process isolation. Future callers
must supply authorized bytes inside the reviewed network-none parser boundary.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal, NoReturn
from xml.parsers import expat

from pydantic import Field, ValidationError, model_validator

from emailmonitor.extraction.html import AuthorFact, CandidateFact, Evidence, Fact
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.sciencedirect import (
    API_ORIGIN,
    ArticleIdentifier,
    article_path,
    normalize_identifier,
)

NS = {
    "api": "http://www.elsevier.com/xml/svapi/article/dtd",
    "xocs": "http://www.elsevier.com/xml/xocs/dtd",
    "ja": "http://www.elsevier.com/xml/ja/dtd",
    "ce": "http://www.elsevier.com/xml/common/dtd",
    "sa": "http://www.elsevier.com/xml/common/struct-aff/dtd",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "xlink": "http://www.w3.org/1999/xlink",
}
MAX_BYTES = 2_097_152
MAX_NODES = 20_000
MAX_DEPTH = 48
MAX_TEXT = 1_048_576
ID = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,99}\Z")
Reason = Literal[
    "missing_full_text",
    "unsupported_structure",
    "missing_article_identity",
    "missing_authors",
    "unsupported_author",
    "ambiguous_reference",
    "unsupported_affiliation",
    "unsupported_email",
    "unstructured_contact",
]


def _tag(name: str) -> str:
    prefix, local = name.split(":", 1)
    return NS[prefix] + "}" + local


class XmlCandidate(CandidateFact):
    # CandidateFact keeps address, identity, technical and outreach states separate.
    association_evidence: list[Evidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def evidence_required(self) -> "XmlCandidate":
        if self.raw_address not in self.evidence.excerpt:
            raise ValueError("Literal address evidence required")
        if bool(self.author_positions) != bool(self.association_evidence):
            raise ValueError("Structural association evidence required")
        return self


class XmlObservation(Fact):
    parser_version: Literal["elsevier-xml-head-v1"] = "elsevier-xml-head-v1"
    route: Literal["article_xml"] = "article_xml"
    source_profile: Literal["article_retrieval_response", "xocs_document", "unknown"]
    url: str = Field(max_length=2048)
    requested_identifier: ArticleIdentifier
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["observed", "no_contact", "partial", "unsupported"]
    reasons: list[Reason] = Field(default_factory=list, max_length=20)
    authors: list[AuthorFact] = Field(default_factory=list, max_length=100)
    candidates: list[XmlCandidate] = Field(default_factory=list, max_length=100)
    identity_association_implemented: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self) -> "XmlObservation":
        if self.url != API_ORIGIN + article_path(self.requested_identifier):
            raise ValueError("Canonical identifier-only source URL required")
        if [a.position for a in self.authors] != list(range(1, len(self.authors) + 1)) or any(
            a.first != (a.position == 1) for a in self.authors
        ):
            raise ValueError("Observed author order required")
        positions = {a.position for a in self.authors}
        for candidate in self.candidates:
            if (
                len(set(candidate.author_positions)) != len(candidate.author_positions)
                or not set(candidate.author_positions) <= positions
                or bool(candidate.author_positions)
                != (candidate.association_status == "needs_review")
            ):
                raise ValueError("Observed structural references required")
        if self.status != "unsupported" and self.source_profile == "unknown":
            raise ValueError("Observed profile must be identified")
        if self.status == "unsupported":
            if not self.reasons or self.authors or self.candidates:
                raise ValueError("Unsupported response cannot assert observations")
        elif not self.authors:
            raise ValueError("Supported profile requires authors")
        if self.status in ("observed", "no_contact") and (
            self.reasons or (self.status == "observed") != bool(self.candidates)
        ):
            raise ValueError("Complete profile outcome must agree with candidates")
        if self.status == "partial" and not self.reasons:
            raise ValueError("Partial outcome requires reason")
        return self


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    locator: str
    children: list["Node"] = field(default_factory=list)
    parts: list["str | Node"] = field(default_factory=list)

    def named(self, name: str) -> list["Node"]:
        return [child for child in self.children if child.tag == _tag(name)]

    def text(self) -> str:
        return "".join(part if isinstance(part, str) else part.text() for part in self.parts)


class _Tree:
    def __init__(self) -> None:
        self.root: Node | None = None
        self.stack: list[Node] = []
        self.nodes: list[Node] = []
        self.characters = 0
        self.ids: set[str] = set()

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        if (
            len(self.nodes) >= MAX_NODES
            or len(self.stack) >= MAX_DEPTH
            or len(attrs) > 32
            or len(tag) > 256
            or any(len(k) > 256 or len(v) > 2048 for k, v in attrs.items())
        ):
            raise FetchDenied("sciencedirect_xml_limit")
        identity = attrs.get("id")
        if identity is not None:
            if not ID.fullmatch(identity) or identity in self.ids:
                raise FetchDenied("sciencedirect_xml_identity_ambiguity")
            self.ids.add(identity)
        parent = self.stack[-1] if self.stack else None
        locator = f"{parent.locator}/{len(parent.children) + 1}" if parent else "xml:/1"
        node = Node(tag, attrs, locator)
        if parent:
            parent.children.append(node)
            parent.parts.append(node)
        else:
            self.root = node
        self.nodes.append(node)
        self.stack.append(node)

    def end(self, tag: str) -> None:
        self.stack.pop()

    def text(self, value: str) -> None:
        self.characters += len(value)
        if self.characters > MAX_TEXT:
            raise FetchDenied("sciencedirect_xml_limit")
        if self.stack:
            self.stack[-1].parts.append(value)


def _forbidden(*args: object) -> NoReturn:
    raise FetchDenied("sciencedirect_xml_unsafe_construct")


def _declaration(version: str, encoding: str | None, standalone: int) -> None:
    if version != "1.0" or (encoding is not None and encoding.lower() != "utf-8"):
        raise FetchDenied("sciencedirect_xml_encoding")


def _tree(data: bytes) -> Node:
    if type(data) is not bytes or not data or len(data) > MAX_BYTES:
        raise FetchDenied("sciencedirect_xml_limit")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise FetchDenied("sciencedirect_xml_encoding") from None
    if any(ord(c) < 32 and c not in "\t\r\n" for c in text):
        raise FetchDenied("sciencedirect_xml_encoding")
    builder = _Tree()
    parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")
    parser.buffer_text = True
    parser.buffer_size = 8192
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.text
    parser.StartDoctypeDeclHandler = _forbidden
    parser.EntityDeclHandler = _forbidden
    parser.ExternalEntityRefHandler = _forbidden
    parser.ProcessingInstructionHandler = _forbidden
    parser.XmlDeclHandler = _declaration
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except expat.ExpatError:
        raise FetchDenied("sciencedirect_xml_malformed") from None
    if builder.root is None:
        raise FetchDenied("sciencedirect_xml_malformed")
    return builder.root


def _one(parent: Node, name: str) -> Node | None:
    matches = parent.named(name)
    if len(matches) > 1:
        raise _Unsupported("unsupported_structure")
    return matches[0] if matches else None


class _Unsupported(Exception):
    def __init__(self, reason: Reason) -> None:
        self.reason = reason


def _value(node: Node, limit: int) -> str:
    value = " ".join(node.text().split())
    if not value or len(value) > limit or any(ord(c) == 127 for c in value):
        raise _Unsupported("unsupported_structure")
    return value


def _evidence(node: Node, value: str | None = None, attribute: str | None = None) -> Evidence:
    return Evidence(
        locator=node.locator + (f"/@{attribute}" if attribute else ""),
        excerpt=(value if value is not None else " ".join(node.text().split()))[:300],
        kind="structured_metadata",
    )


def _identity(parent: Node, name: str, expected: ArticleIdentifier, required: bool) -> None:
    identifier = _one(parent, name)
    if identifier is None:
        if required:
            raise _Unsupported("missing_article_identity")
        return
    if identifier.children:
        raise _Unsupported("unsupported_structure")
    try:
        observed = normalize_identifier(_value(identifier, 256))
    except FetchDenied:
        raise FetchDenied("sciencedirect_xml_article_mismatch") from None
    if observed != expected:
        raise FetchDenied("sciencedirect_xml_article_mismatch")


def _head(root: Node, expected: ArticleIdentifier) -> Node:
    native = root.tag == _tag("xocs:doc")
    core: Node | None = None
    if native:
        document = root
    else:
        if root.tag != _tag("api:full-text-retrieval-response"):
            raise _Unsupported("unsupported_structure")
        core = _one(root, "api:coredata")
        if core is None:
            raise _Unsupported("missing_article_identity")
        _identity(core, "prism:doi" if expected.kind == "doi" else "api:pii", expected, True)
        original = _one(root, "api:originalText")
        if original is None:
            raise _Unsupported("missing_full_text")
        doc = _one(original, "xocs:doc")
        if doc is None:
            raise _Unsupported("unsupported_structure")
        document = doc
    meta = _one(document, "xocs:meta")
    if meta is None:
        if native:
            raise _Unsupported("missing_article_identity")
    else:
        _identity(
            meta, "xocs:doi" if expected.kind == "doi" else "xocs:pii-unformatted", expected, native
        )
        if core is not None:
            for left_name, right_name in (
                ("prism:doi", "xocs:doi"),
                ("api:pii", "xocs:pii-unformatted"),
            ):
                left = _one(core, left_name)
                right = _one(meta, right_name)
                if left is not None and right is not None:
                    try:
                        comparison = normalize_identifier(_value(left, 256))
                    except FetchDenied:
                        raise FetchDenied("sciencedirect_xml_article_mismatch") from None
                    _identity(meta, right_name, comparison, True)
    node = document
    for name in ("xocs:serial-item", "ja:article", "ja:head"):
        next_node = _one(node, name)
        if next_node is None:
            raise _Unsupported("unsupported_structure")
        node = next_node
    return node


def _name(node: Node) -> tuple[str, Literal["person", "group"], list[Evidence]]:
    if node.tag == _tag("ce:collaboration"):
        text = _one(node, "ce:text")
        if text is None or any(
            c.tag not in {_tag("ce:text"), _tag("ce:e-address"), _tag("ce:cross-ref")}
            for c in node.children
        ):
            raise _Unsupported("unsupported_author")
        return _value(text, 300), "group", [_evidence(text)]
    allowed = {
        _tag("ce:" + name)
        for name in (
            "given-name",
            "surname",
            "suffix",
            "initials",
            "indexed-name",
            "degrees",
            "ranking",
            "roles",
            "contributor-role",
            "cross-ref",
            "e-address",
            "link",
        )
    }
    if any(c.tag not in allowed for c in node.children) or node.attrs.get("role"):
        raise _Unsupported("unsupported_author")
    parts = []
    evidence = []
    for name in ("ce:given-name", "ce:surname", "ce:suffix"):
        child = _one(node, name)
        if child:
            if child.children:
                raise _Unsupported("unsupported_author")
            parts.append(_value(child, 300))
            evidence.append(_evidence(child))
    if not parts or len(" ".join(parts)) > 300 or node.named("ce:alt-name"):
        raise _Unsupported("unsupported_author")
    return " ".join(parts), "person", evidence


def _references(node: Node, targets: dict[str, Node]) -> list[tuple[Node, Node]]:
    references = []
    seen: set[str] = set()
    if node.named("ce:cross-refs"):
        # Multiple-ID shorthand is not silently treated as one identifier.
        raise _Unsupported("ambiguous_reference")
    for reference in node.named("ce:cross-ref"):
        key = reference.attrs.get("refid", "")
        target = targets.get(key)
        if not ID.fullmatch(key) or target is None or key in seen:
            raise _Unsupported("ambiguous_reference")
        seen.add(key)
        references.append((reference, target))
    if len(references) > 8:
        raise FetchDenied("sciencedirect_xml_limit")
    return references


def _email(node: Node, positions: list[int], links: list[Evidence]) -> XmlCandidate | None:
    kind = node.attrs.get("type", "email")
    if kind in {"url", "social-media"}:
        return None
    if kind != "email":
        raise _Unsupported("unsupported_email")
    if node.children:
        raise _Unsupported("unsupported_email")
    text = node.text().strip()
    href = node.attrs.get(_tag("xlink:href"))
    address = text or (href.removeprefix("mailto:") if href else "")
    if (
        not 3 <= len(address) <= (300 if text else 293)
        or address.count("@") != 1
        or address.startswith("@")
        or address.endswith("@")
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "<>,;?%" for c in address)
        or (href is not None and href != "mailto:" + address)
    ):
        raise _Unsupported("unsupported_email")
    return XmlCandidate(
        raw_address=address,
        author_positions=positions,
        association_status="needs_review" if positions else "unmatched",
        evidence=_evidence(node, text if text else href, None if text else "xlink:href"),
        association_evidence=links,
    )


def _observe(head: Node) -> tuple[list[AuthorFact], list[XmlCandidate], list[Reason]]:
    groups = head.named("ce:author-group")
    if not groups:
        raise _Unsupported("missing_authors")
    authors: list[AuthorFact] = []
    candidates: list[XmlCandidate] = []
    reasons: list[Reason] = []
    for group in groups:
        allowed = {
            _tag("ce:" + name)
            for name in (
                "author",
                "collaboration",
                "affiliation",
                "correspondence",
                "footnote",
                "text",
            )
        }
        if any(c.tag not in allowed for c in group.children) or group.attrs.get("role"):
            raise _Unsupported("unsupported_structure")
        if any("@" in text.text() for text in group.named("ce:text")):
            reasons.append("unstructured_contact")
        people = [
            c for c in group.children if c.tag in {_tag("ce:author"), _tag("ce:collaboration")}
        ]
        if not people:
            raise _Unsupported("missing_authors")
        targets = {
            child.attrs["id"]: child
            for child in group.children
            if "id" in child.attrs
            and child.tag
            in {_tag("ce:affiliation"), _tag("ce:correspondence"), _tag("ce:footnote")}
        }
        refs = {person: _references(person, targets) for person in people}
        implicit = not any(refs.values()) and all(
            not a.named("ce:label") for a in group.named("ce:affiliation")
        )
        for person in people:
            if len(authors) >= 100:
                raise FetchDenied("sciencedirect_xml_limit")
            position = len(authors) + 1
            name, kind, evidence = _name(person)
            affiliations = []
            selected = [(r, a) for r, a in refs[person] if a.tag == _tag("ce:affiliation")]
            if implicit:
                selected = [(group, a) for a in group.named("ce:affiliation")]
            if not selected and group.named("ce:affiliation"):
                reasons.append("unsupported_affiliation")
            for reference, affiliation in selected:
                text = _one(affiliation, "ce:textfn")
                if text is None:
                    reasons.append("unsupported_affiliation")
                    continue
                affiliations.append(_value(text, 1000))
                evidence.extend(
                    [
                        _evidence(
                            reference,
                            reference.attrs["refid"] if reference is not group else None,
                            "refid" if reference is not group else None,
                        ),
                        _evidence(text),
                    ]
                )
            corresponding: Literal[True] | None = None
            for reference, target in refs[person]:
                if target.tag == _tag("ce:correspondence"):
                    corresponding = True
                    link = _evidence(reference, reference.attrs["refid"], "refid")
                    evidence.extend([link, _evidence(target)])
            if len(evidence) > 20 or len(affiliations) > 20:
                raise FetchDenied("sciencedirect_xml_limit")
            authors.append(
                AuthorFact(
                    position=position,
                    display_name=name,
                    affiliations=affiliations,
                    author_kind=kind,
                    first=position == 1,
                    corresponding=corresponding,
                    evidence=evidence,
                )
            )
            for email in person.named("ce:e-address"):
                try:
                    candidate = _email(email, [position], [_evidence(person)])
                    if candidate:
                        candidates.append(candidate)
                        if len(candidates) > 100:
                            raise FetchDenied("sciencedirect_xml_limit")
                except _Unsupported as error:
                    reasons.append(error.reason)
        for correspondence in group.named("ce:correspondence"):
            if correspondence.named("ce:e-address"):
                reasons.append("unstructured_contact")
            allowed_correspondence = {
                _tag("ce:label"),
                _tag("ce:text"),
                _tag("sa:affiliation"),
                _tag("ce:e-address"),
            }
            if any(c.tag not in allowed_correspondence for c in correspondence.children):
                raise _Unsupported("unsupported_structure")
            text = _one(correspondence, "ce:text")
            if text is None:
                raise _Unsupported("unsupported_structure")
            # Plain prose and nested unsupported elements are never regex-mined.
            if "@" in text.text() or text.named("ce:e-address"):
                reasons.append("unstructured_contact")
    if len(candidates) > 100:
        raise FetchDenied("sciencedirect_xml_limit")
    return authors, candidates, list(dict.fromkeys(reasons))


def parse_article(data: bytes, identifier: ArticleIdentifier) -> XmlObservation:
    """Parse a caller-supplied response, without fetching, persisting or accepting it.

    Invalid XML/security/resource or mismatched-article inputs are denied with a
    fixed reason. Valid but unsupported profiles remain explicit empty outcomes.
    no_contact means no contact in this supported head profile, never the paper.
    """
    source_url = API_ORIGIN + article_path(identifier)
    root = _tree(data)
    digest = hashlib.sha256(data).hexdigest()
    profile: Literal["article_retrieval_response", "xocs_document", "unknown"] = (
        "xocs_document"
        if root.tag == _tag("xocs:doc")
        else "article_retrieval_response"
        if root.tag == _tag("api:full-text-retrieval-response")
        else "unknown"
    )
    try:
        authors, candidates, reasons = _observe(_head(root, identifier))
        return XmlObservation(
            url=source_url,
            requested_identifier=identifier,
            source_profile=profile,
            content_digest=digest,
            status="partial" if reasons else "observed" if candidates else "no_contact",
            authors=authors,
            candidates=candidates,
            reasons=reasons,
        )
    except _Unsupported as error:
        return XmlObservation(
            url=source_url,
            requested_identifier=identifier,
            source_profile=profile,
            content_digest=digest,
            status="unsupported",
            reasons=[error.reason],
        )
    except ValidationError:
        raise FetchDenied("sciencedirect_xml_observation_limit") from None
