"""Unit tests for ORCID Researcher Disambiguation & ISO 7064 Checksum."""

from __future__ import annotations

import pytest

from emailmonitor.extraction.orcid import (
    OrcidAffiliation,
    OrcidIdentifier,
    OrcidProfile,
    calculate_mod11_2_checksum,
    disambiguate_author_match,
    validate_orcid_id,
)


def test_orcid_mod11_2_checksum_calculation() -> None:
    # 0000-0002-1825-0097 (Real Marcus / Elena sample format)
    base_15 = "000000021825009"
    check = calculate_mod11_2_checksum(base_15)
    assert check == "7"

    # Known ORCID ending with 'X'
    # 0000-0002-1825-002X
    base_x = "000000021825002"
    check_x = calculate_mod11_2_checksum(base_x)
    assert check_x == "X"


def test_orcid_validation_valid_and_invalid() -> None:
    assert validate_orcid_id("0000-0002-1825-0097") is True
    assert validate_orcid_id("https://orcid.org/0000-0002-1825-0097") is True
    assert validate_orcid_id("0000-0002-1825-002X") is True

    # Bad check digit
    assert validate_orcid_id("0000-0002-1825-0098") is False
    # Malformed length
    assert validate_orcid_id("0000-0002-1825") is False
    # Non-digit chars
    assert validate_orcid_id("0000-0002-182A-0097") is False


def test_orcid_identifier_from_raw() -> None:
    orcid = OrcidIdentifier.from_raw("https://orcid.org/0000-0002-1825-0097")
    assert orcid.value == "0000-0002-1825-0097"
    assert orcid.uri == "https://orcid.org/0000-0002-1825-0097"

    with pytest.raises(ValueError, match="Invalid ORCID iD"):
        OrcidIdentifier.from_raw("0000-0002-1825-0098")


def test_author_disambiguation_with_affiliation() -> None:
    orcid_1 = OrcidIdentifier(value="0000-0002-1825-0097")
    profile_cambridge = OrcidProfile(
        orcid=orcid_1,
        given_names="Elena",
        family_name="Rostova",
        affiliations=(
            OrcidAffiliation(organization_name="University of Cambridge"),
        ),
        verified_email_domains=("cam.ac.uk",),
    )

    orcid_2 = OrcidIdentifier(value="0000-0002-1825-002X")
    profile_stanford = OrcidProfile(
        orcid=orcid_2,
        given_names="Elena",
        family_name="Rostova",
        affiliations=(
            OrcidAffiliation(organization_name="Stanford University"),
        ),
        verified_email_domains=("stanford.edu",),
    )

    pool = [profile_cambridge, profile_stanford]

    # Disambiguate by Cambridge affiliation
    matched_cam = disambiguate_author_match(
        "Elena Rostova",
        "Department of Genetics, University of Cambridge, UK",
        pool,
    )
    assert matched_cam is not None
    assert matched_cam.orcid.value == "0000-0002-1825-0097"

    # Disambiguate by Stanford affiliation
    matched_stan = disambiguate_author_match(
        "Elena Rostova",
        "School of Medicine, Stanford University, Stanford, CA",
        pool,
    )
    assert matched_stan is not None
    assert matched_stan.orcid.value == "0000-0002-1825-002X"

    # Non-matching affiliation
    matched_none = disambiguate_author_match(
        "Elena Rostova",
        "Tokyo Institute of Technology",
        pool,
    )
    assert matched_none is None
