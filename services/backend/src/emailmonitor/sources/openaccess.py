"""Open Access repository contracts and identifiers; fail-closed governance.

Supports standard scholarly open access repositories:
- Europe PMC & PubMed Central (PMC) full-text JATS XML
- OpenAlex metadata and works
- Crossref DOI resolution
"""

import re
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")
PMC_PATTERN = re.compile(r"^PMC\d{3,10}$", re.IGNORECASE)
OPENALEX_PATTERN = re.compile(r"^W\d{5,15}$")


def _clean_text(value: str) -> str:
    if not value.strip() or any(
        ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value
    ):
        raise ValueError("invalid_text")
    return value.strip()


class PmcIdentifier(Contract):
    kind: Literal["pmcid"] = "pmcid"
    value: Annotated[str, Field(pattern=r"^PMC\d{3,10}$")]

    @field_validator("value", mode="before")
    @classmethod
    def canonical_pmc(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().upper()
        return v


class DoiIdentifier(Contract):
    kind: Literal["doi"] = "doi"
    value: Annotated[str, Field(min_length=5, max_length=256)]

    @field_validator("value")
    @classmethod
    def canonical_doi(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned.startswith("https://doi.org/"):
            cleaned = cleaned.removeprefix("https://doi.org/")
        elif cleaned.startswith("http://doi.org/"):
            cleaned = cleaned.removeprefix("http://doi.org/")
        elif cleaned.startswith("doi:"):
            cleaned = cleaned.removeprefix("doi:")
        if not DOI_PATTERN.match(cleaned):
            raise ValueError("invalid_doi_format")
        return cleaned


class OpenAlexIdentifier(Contract):
    kind: Literal["openalex"] = "openalex"
    value: Annotated[str, Field(pattern=r"^W\d{5,15}$")]

    @field_validator("value", mode="before")
    @classmethod
    def canonical_openalex(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().upper()
        return v


OpenAccessIdentifier = PmcIdentifier | DoiIdentifier | OpenAlexIdentifier


class OpenAccessCapabilities(Contract):
    source_id: Literal["open_access_jats_v1"] = "open_access_jats_v1"
    adapter_version: Literal["1.0.0"] = "1.0.0"
    live_execution: Literal[False] = False
    jats_xml_extraction: Literal[True] = True
    openalex_metadata: Literal[True] = True
    crossref_metadata: Literal[True] = True


EUROPE_PMC_API: Literal["https://www.ebi.ac.uk/europepmc/webservices/rest"] = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest"
)
OPENALEX_API: Literal["https://api.openalex.org"] = "https://api.openalex.org"
CROSSREF_API: Literal["https://api.crossref.org"] = "https://api.crossref.org"


def open_access_url(identifier: OpenAccessIdentifier) -> str:
    """Produce the canonical API or retrieval URL for an open access identifier."""
    if identifier.kind == "pmcid":
        return f"{EUROPE_PMC_API}/{identifier.value}/fullTextXML"
    if identifier.kind == "doi":
        return f"{CROSSREF_API}/works/{quote(identifier.value, safe='')}"
    if identifier.kind == "openalex":
        return f"{OPENALEX_API}/works/{identifier.value}"
    raise ValueError("unsupported_open_access_identifier")
