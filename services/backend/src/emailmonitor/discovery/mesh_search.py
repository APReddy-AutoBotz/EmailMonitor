"""Medical Subject Headings (MeSH) & Thematic Issue Sourcing Engine.

Translates high-level editor requests for Special Issues into canonical
MeSH descriptors, constructs Boolean queries for Open Access scholarly APIs,
and excludes authors from specified target journals to prevent contributor spam.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    """Immutable contract forbidding extra attributes."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MeshDescriptor(Contract):
    """Canonical Medical Subject Heading (MeSH) entry."""

    descriptor_id: Annotated[str, Field(pattern=r"^D\d{6,9}$")]
    name: str
    tree_numbers: tuple[str, ...] = Field(default_factory=tuple)
    synonyms: tuple[str, ...] = Field(default_factory=tuple)
    scope_note: str | None = None


# Authoritative synthetic reference catalog of high-impact MeSH descriptors
COMMON_MESH_CATALOG: dict[str, MeshDescriptor] = {
    "D000089822": MeshDescriptor(
        descriptor_id="D000089822",
        name="CRISPR-Cas Systems",
        tree_numbers=("G02.111.570.820.709.275", "G05.360.080"),
        synonyms=(
            "CRISPR-Cas9",
            "Cas9",
            "Clustered Regularly Interspaced Short Palindromic Repeats",
        ),
        scope_note="Adaptive immune system in prokaryotes used for precision genome editing.",
    ),
    "D009369": MeshDescriptor(
        descriptor_id="D009369",
        name="Neoplasms",
        tree_numbers=("C04",),
        synonyms=("Cancer", "Tumors", "Malignancy", "Oncology"),
        scope_note="New, abnormal growth of tissue resulting from uncontrolled cell division.",
    ),
    "D007167": MeshDescriptor(
        descriptor_id="D007167",
        name="Immunotherapy",
        tree_numbers=("E02.095.465", "E02.631"),
        synonyms=("Immune Therapy", "Immunologic Therapy", "Checkpoint Inhibitor"),
        scope_note=(
            "Treatment of disease by inducing, enhancing, or suppressing an immune response."
        ),
    ),
    "D009203": MeshDescriptor(
        descriptor_id="D009203",
        name="Myocardial Infarction",
        tree_numbers=("C14.280.647.500", "C14.907.585.500"),
        synonyms=("Heart Attack", "Cardiac Infarction", "MI"),
        scope_note="Necrosis of the myocardium as a result of interruption of blood supply.",
    ),
    "D014612": MeshDescriptor(
        descriptor_id="D014612",
        name="Vaccines",
        tree_numbers=("D20.215.894", "D27.505.954.918"),
        synonyms=("mRNA Vaccines", "Immunization", "Vaccination"),
        scope_note="Suspensions of killed or attenuated microorganisms administered for immunity.",
    ),
}


class ThematicSearchPlanner(Contract):
    """Plans targeted editorial sourcing queries for specific thematic collections."""

    primary_topic: str
    mesh_descriptor_ids: tuple[str, ...] = Field(default_factory=tuple)
    excluded_journals: tuple[str, ...] = Field(default_factory=tuple)
    recent_months: int = Field(default=12, ge=1, le=60)
    keywords_must: tuple[str, ...] = Field(default_factory=tuple)
    keywords_must_not: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def resolved_mesh_terms(self) -> tuple[MeshDescriptor, ...]:
        """Resolve descriptor IDs to full MeSH catalog objects."""
        return tuple(
            COMMON_MESH_CATALOG[desc_id]
            for desc_id in self.mesh_descriptor_ids
            if desc_id in COMMON_MESH_CATALOG
        )

    def to_europepmc_query(self) -> str:
        """Generate canonical query string for Europe PMC API."""
        clauses: list[str] = [f'"{self.primary_topic}"']

        for desc in self.resolved_mesh_terms:
            clauses.append(f'(MESH:"{desc.name}")')

        for kw in self.keywords_must:
            clauses.append(f'"{kw}"')

        for not_kw in self.keywords_must_not:
            clauses.append(f'NOT "{not_kw}"')

        for journal in self.excluded_journals:
            clauses.append(f'NOT JOURNAL:"{journal}"')

        return " AND ".join(clauses)

    def to_openalex_filter_query(self) -> str:
        """Generate search string suitable for OpenAlex works endpoint."""
        tokens = [self.primary_topic]
        tokens.extend(self.keywords_must)
        return " ".join(tokens)

    def is_journal_excluded(self, journal_title: str | None) -> bool:
        """Check if an article's journal matches any excluded journal rules."""
        if not journal_title:
            return False
        clean_target = journal_title.strip().lower()
        for excluded in self.excluded_journals:
            if excluded.strip().lower() in clean_target:
                return True
        return False


def match_mesh_terms(query_text: str) -> tuple[MeshDescriptor, ...]:
    """Scan natural language query text to suggest matching MeSH descriptors."""
    clean_q = query_text.strip().lower()
    if not clean_q:
        return ()

    matches: list[MeshDescriptor] = []
    for desc in COMMON_MESH_CATALOG.values():
        name_lower = desc.name.lower()
        if clean_q in name_lower or name_lower in clean_q:
            matches.append(desc)
            continue
        for syn in desc.synonyms:
            syn_lower = syn.lower()
            if clean_q in syn_lower or syn_lower in clean_q:
                matches.append(desc)
                break

    return tuple(matches)

    return tuple(matches)
