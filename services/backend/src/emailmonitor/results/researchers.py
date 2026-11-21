"""Researcher-level rollup of address observations across articles (OA-017).

Grouping rules follow docs/07 ("never merge two people merely because their
names or shared mailbox match"):

* Observations with the same address comparison key form one profile.
* Two addresses join one profile only when both carry the *same*
  in-article-declared ORCID with a valid check digit. Names never merge.
* Conflicts are surfaced, not resolved: one address observed with two
  different valid ORCIDs, or under materially different author names, is
  flagged for review.

Recency here is the latest publication year actually observed; no activity
is inferred beyond the evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.discovery.openaccess_orchestrator import ExtractedAcademicContact
from emailmonitor.results.oa_exports import write_rows_withholding
from emailmonitor.results.outreach import current_year


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


LINKING_BASES = frozenset({"contrib_email", "corresp_xref", "highwire_author_sequence"})

PublicationRole = Literal["corresponding", "first", "first_and_corresponding", "other", "unknown"]


class ResearcherPublication(Contract):
    contact_id: str
    email: str
    doi: str | None
    pmcid: str | None
    title: str | None
    journal: str | None
    publication_year: int | None
    role: PublicationRole
    affiliation: str | None
    association_basis: str
    content_digest: str


class ResearcherProfile(Contract):
    researcher_key: str
    display_names: tuple[str, ...]
    emails: tuple[str, ...]
    orcids: tuple[str, ...]
    publications: tuple[ResearcherPublication, ...]
    publication_count: int = Field(ge=1)
    corresponding_count: int = Field(ge=0)
    first_author_count: int = Field(ge=0)
    latest_publication_year: int | None
    latest_affiliation: str | None
    affiliation_changed: bool
    activity: Literal["active_recent", "moderate", "dormant", "unknown"]
    outreach_eligibility: Literal["eligible", "needs_review", "suppressed"]
    review_flags: tuple[str, ...]


def _role(contact: ExtractedAcademicContact) -> PublicationRole:
    if contact.author_name is None:
        return "unknown"
    if contact.is_first_author and contact.is_corresponding_author:
        return "first_and_corresponding"
    if contact.is_corresponding_author:
        return "corresponding"
    if contact.is_first_author:
        return "first"
    return "other"


def _name_key(name: str) -> str:
    return " ".join(name.casefold().replace(".", " ").split())


def _names_conflict(names: Sequence[str]) -> bool:
    """True when names share no surname token (e.g. two different people on one mailbox)."""
    surnames = {_name_key(n).split()[-1] for n in names if _name_key(n)}
    return len(surnames) > 1


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def build_researcher_profiles(
    contacts: Iterable[ExtractedAcademicContact],
    reference_year: int | None = None,
) -> tuple[ResearcherProfile, ...]:
    ref = reference_year or current_year()
    items = list(contacts)
    uf = _UnionFind()
    # Link addresses only through an ORCID that (a) the article declares on the
    # author, (b) is tied to the address by a structural basis, not a text
    # heuristic, and (c) is the address's only ORCID. An address seen with two
    # ORCIDs (a shared mailbox) never bridges two people.
    orcids_by_address: dict[str, set[str]] = {}
    for c in items:
        uf.find(c.comparison_key)
        if c.orcid_id and c.orcid_status == "declared_valid_checksum":
            orcids_by_address.setdefault(c.comparison_key, set()).add(c.orcid_id)
    orcid_owner: dict[str, str] = {}
    for c in items:
        if (
            c.orcid_id
            and c.orcid_status == "declared_valid_checksum"
            and c.association_basis in LINKING_BASES
            and len(orcids_by_address.get(c.comparison_key, ())) == 1
        ):
            owner = orcid_owner.setdefault(c.orcid_id, c.comparison_key)
            uf.union(owner, c.comparison_key)

    groups: dict[str, list[ExtractedAcademicContact]] = {}
    for c in items:
        groups.setdefault(uf.find(c.comparison_key), []).append(c)

    profiles: list[ResearcherProfile] = []
    for root, members in groups.items():
        members.sort(key=lambda c: (-(c.publication_year or 0), c.contact_id))
        seen_articles: set[tuple[str, str]] = set()
        publications: list[ResearcherPublication] = []
        for c in members:
            article = c.doi or c.pmcid or c.content_digest
            if (article, c.comparison_key) in seen_articles:
                continue
            seen_articles.add((article, c.comparison_key))
            publications.append(
                ResearcherPublication(
                    contact_id=c.contact_id,
                    email=c.email,
                    doi=c.doi,
                    pmcid=c.pmcid,
                    title=c.article_title,
                    journal=c.journal,
                    publication_year=c.publication_year,
                    role=_role(c),
                    affiliation=c.affiliations[0] if c.affiliations else None,
                    association_basis=c.association_basis,
                    content_digest=c.content_digest,
                )
            )

        names = tuple(dict.fromkeys(c.author_name for c in members if c.author_name))
        emails = tuple(dict.fromkeys(c.email for c in members))
        orcids = tuple(
            dict.fromkeys(
                c.orcid_id
                for c in members
                if c.orcid_id and c.orcid_status == "declared_valid_checksum"
            )
        )
        years = [p.publication_year for p in publications if p.publication_year is not None]
        latest = max(years) if years else None
        dated_affiliations = [
            (p.publication_year or 0, p.affiliation) for p in publications if p.affiliation
        ]
        latest_affiliation = max(dated_affiliations)[1] if dated_affiliations else None
        distinct_affiliations = {a.casefold() for _y, a in dated_affiliations}

        flags: list[str] = []
        by_address: dict[str, set[str]] = {}
        for c in members:
            if c.orcid_id and c.orcid_status == "declared_valid_checksum":
                by_address.setdefault(c.comparison_key, set()).add(c.orcid_id)
        if any(len(v) > 1 for v in by_address.values()):
            flags.append("address_has_conflicting_orcids")
        if _names_conflict(names):
            flags.append("address_used_under_different_names")
        if not names:
            flags.append("no_author_association")
        if any(c.orcid_status == "declared_invalid_checksum" for c in members):
            flags.append("invalid_orcid_declared")
        if len(emails) > 1:
            flags.append("multiple_addresses_linked_by_orcid")

        if latest is None:
            activity: Literal["active_recent", "moderate", "dormant", "unknown"] = "unknown"
        elif ref - latest <= 1:
            activity = "active_recent"
        elif ref - latest <= 3:
            activity = "moderate"
        else:
            activity = "dormant"

        states = {c.outreach_eligibility for c in members}
        if "suppressed" in states:
            eligibility: Literal["eligible", "needs_review", "suppressed"] = "suppressed"
        elif "eligible" in states and not (
            {"address_has_conflicting_orcids", "address_used_under_different_names"} & set(flags)
        ):
            eligibility = "eligible"
        else:
            eligibility = "needs_review"

        profiles.append(
            ResearcherProfile(
                researcher_key=f"r-{root}" if len(root) <= 330 else f"r-{root[:330]}",
                display_names=names,
                emails=emails,
                orcids=orcids,
                publications=tuple(publications),
                publication_count=len(publications),
                corresponding_count=sum(
                    1
                    for p in publications
                    if p.role in ("corresponding", "first_and_corresponding")
                ),
                first_author_count=sum(
                    1 for p in publications if p.role in ("first", "first_and_corresponding")
                ),
                latest_publication_year=latest,
                latest_affiliation=latest_affiliation,
                affiliation_changed=len(distinct_affiliations) > 1,
                activity=activity,
                outreach_eligibility=eligibility,
                review_flags=tuple(flags),
            )
        )

    profiles.sort(
        key=lambda p: (
            -(p.latest_publication_year or 0),
            -p.corresponding_count,
            -p.publication_count,
            p.researcher_key,
        )
    )
    return tuple(profiles)


def render_researchers_export(profiles: Sequence[ResearcherProfile]) -> tuple[bytes, int, int]:
    """One row per researcher; a row with a formula-unsafe cell is withheld, not rewritten.

    Returns (content, rows_written, rows_withheld).
    """
    header = [
        "primary_email",
        "other_emails",
        "names",
        "orcids",
        "latest_publication_year",
        "latest_affiliation",
        "affiliation_changed",
        "publications",
        "corresponding_count",
        "first_author_count",
        "activity",
        "outreach_eligibility",
        "review_flags",
        "latest_title",
        "latest_doi",
    ]
    rows: list[list[str]] = []
    for p in profiles:
        latest = p.publications[0]
        rows.append(
            [
                p.emails[0],
                "; ".join(p.emails[1:]),
                "; ".join(p.display_names),
                "; ".join(p.orcids),
                str(p.latest_publication_year or ""),
                p.latest_affiliation or "",
                "yes" if p.affiliation_changed else "no",
                str(p.publication_count),
                str(p.corresponding_count),
                str(p.first_author_count),
                p.activity,
                p.outreach_eligibility,
                "; ".join(p.review_flags),
                latest.title or "",
                latest.doi or "",
            ]
        )
    return write_rows_withholding(header, rows)


def render_researchers_csv(profiles: Sequence[ResearcherProfile]) -> bytes:
    return render_researchers_export(profiles)[0]
