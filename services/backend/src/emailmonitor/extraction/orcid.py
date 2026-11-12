"""ORCID Researcher Disambiguation & Identity Verification.

Provides ISO 7064, MOD 11-2 check-digit verification for ORCID iDs,
normalizes canonical ORCID URIs, and disambiguates common author names
across scholarly repositories to prevent cross-researcher contact collision.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    """Immutable base model forbidding extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def calculate_mod11_2_checksum(base_digits: str) -> str:
    """Compute ISO 7064 MOD 11-2 check character for the first 15 digits."""
    total = 0
    for char in base_digits:
        total = (total + int(char)) * 2
    remainder = total % 11
    result = (12 - remainder) % 11
    return "X" if result == 10 else str(result)


def validate_orcid_id(orcid_str: str) -> bool:
    """Validate 16-character hyphenated ORCID format with MOD 11-2 check digit."""
    clean = orcid_str.strip()
    if clean.startswith("https://orcid.org/"):
        clean = clean.replace("https://orcid.org/", "")
    elif clean.startswith("http://orcid.org/"):
        clean = clean.replace("http://orcid.org/", "")

    pattern = r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"
    if not re.match(pattern, clean):
        return False

    digits_only = clean.replace("-", "")
    base_15 = digits_only[:15]
    expected_check = calculate_mod11_2_checksum(base_15)
    return digits_only[15] == expected_check


class OrcidIdentifier(Contract):
    """Verified, canonical ORCID iD with verified checksum."""

    value: Annotated[str, Field(pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")]

    @classmethod
    def from_raw(cls, raw: str) -> OrcidIdentifier:
        clean = raw.strip()
        if clean.startswith("https://orcid.org/"):
            clean = clean.replace("https://orcid.org/", "")
        elif clean.startswith("http://orcid.org/"):
            clean = clean.replace("http://orcid.org/", "")

        if not validate_orcid_id(clean):
            raise ValueError(f"Invalid ORCID iD checksum or format: {raw}")
        return cls(value=clean)

    @property
    def uri(self) -> str:
        """Return the canonical HTTPS URI for this ORCID iD."""
        return f"https://orcid.org/{self.value}"


class OrcidAffiliation(Contract):
    """Institutional affiliation associated with an ORCID record."""

    organization_name: str
    department: str | None = None
    city: str | None = None
    country: str | None = None
    role_title: str | None = None
    start_year: int | None = None
    end_year: int | None = None


class OrcidProfile(Contract):
    """Canonical disambiguated researcher identity record."""

    orcid: OrcidIdentifier
    given_names: str
    family_name: str
    credit_name: str | None = None
    affiliations: tuple[OrcidAffiliation, ...] = Field(default_factory=tuple)
    verified_email_domains: tuple[str, ...] = Field(default_factory=tuple)
    keywords: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def display_name(self) -> str:
        return self.credit_name or f"{self.given_names} {self.family_name}"


def disambiguate_author_match(
    candidate_name: str,
    candidate_affiliation: str | None,
    profiles: list[OrcidProfile],
) -> OrcidProfile | None:
    """Match an extracted author name and institution against verified ORCID profiles.

    Strictly matches by name and verifies institution overlap to avoid false positives.
    """
    clean_target = candidate_name.strip().lower()
    for profile in profiles:
        names = [
            profile.display_name.lower(),
            f"{profile.given_names.lower()} {profile.family_name.lower()}",
            f"{profile.family_name.lower()} {profile.given_names.lower()}",
        ]
        if profile.credit_name:
            names.append(profile.credit_name.lower())

        if any(clean_target == n for n in names):
            if candidate_affiliation:
                aff_lower = candidate_affiliation.lower()
                for aff in profile.affiliations:
                    if (
                        aff.organization_name.lower() in aff_lower
                        or aff_lower in aff.organization_name.lower()
                    ):
                        return profile
            else:
                return profile
    return None
