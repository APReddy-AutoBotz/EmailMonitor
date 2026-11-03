"""Inert bounded observations, never accepted identities or permission grants.

The synthetic connector recognizes explicit article/author/correspondence blocks.
Acquired untrusted bytes belong in the network-none parser. This module has no
network, browser, script evaluation, sending, or expected-results dependency.
"""

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Annotated, Literal
from urllib.parse import unquote, urljoin

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.config import Settings
from emailmonitor.discovery.planning import ARTICLE_PATHS
from emailmonitor.fetching.fixture import HOSTS, require_fixture
from emailmonitor.fetching.safety import FetchDenied, classify_url

VERSION: Literal["synthetic-html-v1"] = "synthetic-html-v1"
VOID = frozenset({"meta", "link", "img", "br", "hr", "input", "source", "wbr"})
INERT = frozenset({"script", "style", "template", "noscript"})
EXCLUDED = frozenset({"footer", "nav", "aside", "form", "references", "advertisement"})
ADDRESS = re.compile(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w.-]+")


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def false_is_boolean(cls, value: object) -> object:
        if isinstance(value, dict):
            for name in ("identity_association_implemented", "scheduled"):
                if name in value and value[name] is not False:
                    raise ValueError("Unavailable capability requires boolean false")
        return value


class Evidence(Fact):
    locator: str = Field(min_length=1, max_length=512)
    excerpt: str = Field(max_length=300)
    kind: Literal["structured_metadata", "article_dom", "mailto", "public_attribute", "browser_dom"]


class MetadataFact(Fact):
    field: Literal["title", "journal", "publication_date", "doi"]
    value: str = Field(min_length=1, max_length=1000)
    date_type: Literal["published", "unspecified"] = "unspecified"
    evidence: Evidence


class MetadataValues(Fact):
    title: str | None = Field(default=None, max_length=1000)
    journal: str | None = Field(default=None, max_length=1000)
    publication_date: str | None = Field(default=None, max_length=1000)
    doi: str | None = Field(default=None, max_length=1000)


class AuthorFact(Fact):
    position: int = Field(ge=1, le=100)
    display_name: str = Field(min_length=1, max_length=300)
    affiliations: list[Annotated[str, Field(max_length=1000)]] = Field(max_length=20)
    orcid: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$")
    author_kind: Literal["person", "group", "unknown"] = "unknown"
    first: bool
    corresponding: bool | None
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


class CandidateFact(Fact):
    raw_address: str = Field(min_length=1, max_length=320)
    # Structural name references are observations, not accepted associations.
    author_positions: list[Annotated[int, Field(ge=1, le=100)]] = Field(max_length=100)
    association_status: Literal["unmatched", "needs_review"]
    technical_status: Literal["not_checked"] = "not_checked"
    delivery_status: Literal["unverified"] = "unverified"
    outreach_eligibility: Literal["not_assessed"] = "not_assessed"
    evidence: Evidence


class FollowUpFact(Fact):
    url: str = Field(max_length=2048)
    depth: int = Field(ge=1, le=2)
    scheduled: Literal[False] = False
    evidence: Evidence


class ArticleObservation(Fact):
    schema_version: Literal["1.0"] = "1.0"
    url: str = Field(max_length=2048)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: Literal["synthetic-html-v1"] = VERSION
    route: Literal["html", "browser_dom"]
    status: Literal["observed", "no_contact", "requires_browser"]
    metadata: list[MetadataFact] = Field(max_length=100)
    preferred_metadata: MetadataValues
    authors: list[AuthorFact] = Field(max_length=100)
    candidates: list[CandidateFact] = Field(max_length=100)
    follow_up: list[FollowUpFact] = Field(max_length=20)
    browser_plan: Literal["synthetic-tooltip-v1"] | None = None
    identity_association_implemented: Literal[False] = False

    @model_validator(mode="after")
    def observation_consistency(self) -> "ArticleObservation":
        if self.url not in {"https://synthetic.publisher.example" + path for path in ARTICLE_PATHS}:
            raise ValueError("Registered article URL required")
        if [author.position for author in self.authors] != list(
            range(1, len(self.authors) + 1)
        ) or not self.authors:
            raise ValueError("Contiguous observed author order required")
        if any(author.first != (author.position == 1) for author in self.authors):
            raise ValueError("First author must preserve observed order")
        if (self.status == "observed") != bool(self.candidates):
            raise ValueError("Observation status must agree with candidates")
        if (
            self.route == "browser_dom"
            and self.url != "https://synthetic.publisher.example/tooltip.html"
        ):
            raise ValueError("Registered tooltip browser route required")
        if self.status == "requires_browser" and (
            self.url != "https://synthetic.publisher.example/tooltip.html"
            or self.route != "html"
            or self.browser_plan != "synthetic-tooltip-v1"
        ):
            raise ValueError("Registered unresolved browser plan required")
        if self.status != "requires_browser" and self.browser_plan is not None:
            raise ValueError("Resolved observations cannot retain pending browser plan")
        selected = select_metadata(self.metadata)
        if self.preferred_metadata != selected:
            raise ValueError(
                "Preferred metadata must retain observed precedence; missing fields are null"
            )
        positions = {author.position for author in self.authors}
        for candidate in self.candidates:
            if (
                len(set(candidate.author_positions)) != len(candidate.author_positions)
                or not set(candidate.author_positions) <= positions
            ):
                raise ValueError("Candidate structural references require observed authors")
            if bool(candidate.author_positions) != (candidate.association_status == "needs_review"):
                raise ValueError("Structural reference is not an accepted association")
        return self


def select_metadata(facts: list[MetadataFact]) -> MetadataValues:
    selected: dict[str, str | None] = {}
    for name in ("title", "journal", "publication_date", "doi"):
        matching = [fact for fact in facts if fact.field == name]
        preferred = next(
            (fact for fact in matching if fact.evidence.kind == "structured_metadata"),
            matching[0] if matching else None,
        )
        selected[name] = preferred.value if preferred else None
    return MetadataValues.model_validate(selected)


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str | None]
    locator: str
    children: list["Node | str"] = field(default_factory=list)
    parent: "Node | None" = None

    def ancestors(self) -> list["Node"]:
        result: list[Node] = []
        node: Node | None = self
        while node is not None:
            result.append(node)
            node = node.parent
        return result

    def blocked(self) -> bool:
        return any(
            node.tag in INERT | EXCLUDED
            or bool(set((node.attrs.get("class") or "").split()) & EXCLUDED)
            or (node.attrs.get("id") or "").lower() in EXCLUDED
            or "hidden" in node.attrs
            or node.attrs.get("aria-hidden") == "true"
            or any(
                hidden in re.sub(r"\s+", "", node.attrs.get("style") or "").lower()
                for hidden in ("display:none", "visibility:hidden")
            )
            for node in self.ancestors()
        )

    def text(self, omit_roles: bool = False) -> str:
        if self.blocked() or (
            omit_roles and (self.tag == "sup" or self.attrs.get("class") == "affiliation")
        ):
            return ""
        result = " ".join(
            child if isinstance(child, str) else child.text(omit_roles) for child in self.children
        )
        return " ".join(result.split())


class Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, "root")
        self.stack = [self.root]
        self.nodes: list[Node] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.nodes) >= 2048 or len(self.stack) > 64 or len(attrs) > 35:
            raise FetchDenied("article_parse_limit")
        if len({key for key, _ in attrs}) != len(attrs):
            raise FetchDenied("article_attribute_ambiguity")
        if len(tag) > 64 or any(len(key) > 100 or len(value or "") > 8192 for key, value in attrs):
            raise FetchDenied("article_parse_limit")
        parent = self.stack[-1]
        siblings = sum(isinstance(child, Node) and child.tag == tag for child in parent.children)
        node = Node(tag, dict(attrs), f"{parent.locator}/{tag}[{siblings + 1}]", parent=parent)
        if len(node.locator) > 512:
            raise FetchDenied("article_parse_limit")
        parent.children.append(node)
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise FetchDenied("article_structure_ambiguous")
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _evidence(node: Node, kind: str, value: str | None = None) -> Evidence:
    return Evidence.model_validate(
        {"locator": node.locator, "excerpt": (value or node.text())[:300], "kind": kind}
    )


def _name_present(name: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


def _correspondence(node: Node) -> bool:
    return any(
        ancestor.attrs.get("id") == "correspondence"
        or (ancestor.attrs.get("aria-label") or "").lower()
        in {"corresponding author", "corresponding authors"}
        for ancestor in node.ancestors()
    )


def parse_article(
    settings: Settings,
    url: str,
    payload: bytes,
    *,
    browser_dom: bool = False,
    depth: int = 0,
    acquisition_digest: str | None = None,
    max_depth: int = 2,
) -> ArticleObservation:
    require_fixture(settings)
    safe = classify_url(url, HOSTS)
    if (
        safe.path not in ARTICLE_PATHS
        or type(payload) is not bytes
        or len(payload) > 32768
        or not 0 <= depth <= max_depth <= 2
    ):
        raise FetchDenied("article_parse_limit")
    try:
        html = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise FetchDenied("article_encoding_denied") from None
    document = Document()
    document.feed(html)
    document.close()
    if len(document.stack) != 1:
        raise FetchDenied("article_structure_ambiguous")
    visible = [node for node in document.nodes if not node.blocked()]
    main = [node for node in visible if node.tag == "main"]
    author_lists = [
        node
        for node in visible
        if node.tag == "ol"
        and node.attrs.get("class") == "authors"
        and any(a.tag == "main" for a in node.ancestors())
    ]
    if len(main) != 1 or len(author_lists) != 1:
        raise FetchDenied("article_selectors_changed")
    author_nodes = [
        child
        for child in author_lists[0].children
        if isinstance(child, Node) and child.tag == "li" and not child.blocked()
    ]
    if not author_nodes or len(author_nodes) > 100:
        raise FetchDenied("article_author_limit")
    authors: list[AuthorFact] = []
    correspondence_nodes = [node for node in visible if _correspondence(node)]
    for position, node in enumerate(author_nodes, 1):
        name = node.text(omit_roles=True)
        if not name or len(name) > 300:
            raise FetchDenied("article_author_ambiguous")
        role = [
            item
            for item in correspondence_nodes
            if re.match(
                r"^[\s*]*Corresponding authors?:\s*" + re.escape(name) + r"(?!\w)",
                item.text(),
                re.IGNORECASE,
            )
        ]
        # An explicitly labeled corresponding-author section supplies role
        # evidence only if a bounded paragraph identifies this exact name.
        role += [
            item
            for item in correspondence_nodes
            if item.tag == "p"
            and item.text().startswith(name + ":")
            and any(
                (a.attrs.get("aria-label") or "").lower()
                in {"corresponding author", "corresponding authors"}
                for a in item.ancestors()
            )
        ]
        if (
            sum(other.text(omit_roles=True).casefold() == name.casefold() for other in author_nodes)
            > 1
        ):
            role = []
        affiliation = [
            item.text()
            for item in visible
            if item.attrs.get("class") == "affiliation" and node in item.ancestors()
        ]
        authors.append(
            AuthorFact(
                position=position,
                display_name=name,
                affiliations=affiliation,
                orcid=node.attrs.get("data-orcid"),
                author_kind="group"
                if node.attrs.get("data-author-kind") == "group"
                else "person"
                if node.attrs.get("data-author-kind") == "person"
                else "unknown",
                first=position == 1,
                corresponding=True if role else None,
                evidence=[
                    _evidence(node, "article_dom"),
                    *[_evidence(item, "article_dom") for item in role[:19]],
                ],
            )
        )
    metadata: list[MetadataFact] = []
    citation_fields = {
        "citation_title": "title",
        "citation_journal_title": "journal",
        "citation_publication_date": "publication_date",
        "citation_doi": "doi",
    }
    for node in visible:
        value = node.attrs.get("content")
        if node.tag == "meta" and node.attrs.get("name") in citation_fields and value:
            metadata.append(
                MetadataFact.model_validate(
                    {
                        "field": citation_fields[str(node.attrs["name"])],
                        "value": value,
                        "evidence": _evidence(node, "structured_metadata", value),
                    }
                )
            )
        elif any(a.tag == "main" for a in node.ancestors()):
            field_name = (
                "title"
                if node.tag == "h1"
                else "journal"
                if node.attrs.get("class") == "journal"
                else "publication_date"
                if node.tag == "time" and node.attrs.get("datetime")
                else None
            )
            if field_name:
                value = (
                    str(node.attrs["datetime"]) if field_name == "publication_date" else node.text()
                )
                if value:
                    metadata.append(
                        MetadataFact.model_validate(
                            {
                                "field": field_name,
                                "value": value,
                                "date_type": "published"
                                if field_name == "publication_date"
                                else "unspecified",
                                "evidence": _evidence(node, "article_dom", value),
                            }
                        )
                    )
    candidates: list[CandidateFact] = []
    seen: set[tuple[str, str, str]] = set()
    for node in visible:
        in_author = any(author in node.ancestors() for author in author_nodes)
        if not (_correspondence(node) or in_author):
            continue
        raw_values: list[tuple[str, str]] = []
        href = node.attrs.get("href") or ""
        if node.tag == "a" and href.lower().startswith("mailto:"):
            # Query subject/body/cc/bcc are never additional contact evidence.
            raw_values.append(
                (unquote(href[7:].split("?", 1)[0].split("#", 1)[0]).split("?", 1)[0], "mailto")
            )
        for attr in ("title", "aria-label", "data-contact-email"):
            value = node.attrs.get(attr)
            if value:
                raw_values.append((value, "public_attribute"))
        if node.tag in {"p", "span"} and (
            node.attrs.get("role") == "tooltip"
            or not any(isinstance(child, Node) for child in node.children)
        ):
            raw_values.append((node.text(), "browser_dom" if browser_dom else "article_dom"))
        for raw, kind in raw_values:
            if len(raw) > 1000:
                raise FetchDenied("article_contact_limit")
            for match in ADDRESS.finditer(raw):
                address = match.group().rstrip(".")
                if len(address) > 320:
                    raise FetchDenied("article_contact_limit")
                identity = (address, node.locator, kind)
                if identity in seen:
                    continue
                seen.add(identity)
                scope = node
                while (
                    scope.parent is not None
                    and scope.tag not in {"p", "li"}
                    and scope.attrs.get("id") != "correspondence"
                ):
                    scope = scope.parent
                positions = [
                    author.position
                    for author in authors
                    if _name_present(author.display_name, scope.text())
                ]
                candidates.append(
                    CandidateFact.model_validate(
                        {
                            "raw_address": address,
                            "author_positions": positions,
                            "association_status": "needs_review" if positions else "unmatched",
                            "evidence": _evidence(node, kind, raw),
                        }
                    )
                )
                if len(candidates) > 100:
                    raise FetchDenied("article_contact_limit")
    follows: list[FollowUpFact] = []
    if depth < max_depth:
        for node in visible:
            if (
                node.tag == "a"
                and node.attrs.get("rel") == "full-text"
                and any(a.tag == "main" for a in node.ancestors())
            ):
                target = classify_url(urljoin(safe.normalized, node.attrs.get("href") or ""), HOSTS)
                if target.path not in ARTICLE_PATHS:
                    raise FetchDenied("article_followup_denied")
                follows.append(
                    FollowUpFact(
                        url=target.normalized,
                        depth=depth + 1,
                        evidence=_evidence(node, "article_dom"),
                    )
                )
    reveal = [
        node
        for node in visible
        if node.tag == "button"
        and node.attrs.get("type") == "button"
        and node.attrs.get("id") == "contact-reveal"
        and node.attrs.get("aria-describedby") == "contact-tooltip"
        and _correspondence(node)
    ]
    pending = (
        not browser_dom and safe.path == "/tooltip.html" and len(reveal) == 1 and not candidates
    )
    return ArticleObservation(
        url=safe.normalized,
        content_digest=hashlib.sha256(payload).hexdigest(),
        acquisition_digest=acquisition_digest or hashlib.sha256(payload).hexdigest(),
        route="browser_dom" if browser_dom else "html",
        status="observed" if candidates else "requires_browser" if pending else "no_contact",
        metadata=metadata,
        preferred_metadata=select_metadata(metadata),
        authors=authors,
        candidates=candidates,
        follow_up=follows,
        browser_plan="synthetic-tooltip-v1" if pending else None,
    )
