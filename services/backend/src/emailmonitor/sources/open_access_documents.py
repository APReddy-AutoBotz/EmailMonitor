"""Server-owned registry of Open Access fixture documents (OA-029, document 91).

Each entry binds a durable synthetic article path to one committed synthetic JATS
file, its exact SHA-256 and the Europe PMC full-text URL it stands in for. The
canonical URL is provenance only: nothing in this module or its callers fetches
it. The same entries are pinned by migration 0027 and checked by the database
guard, so code and SQL cannot drift apart silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import PmcIdentifier, open_access_url

SOURCE: Literal["synthetic-publisher"] = "synthetic-publisher"
ORIGIN = "https://synthetic.publisher.example"
PROVIDER: Literal["europe-pmc"] = "europe-pmc"
FIXTURES = Path(__file__).resolve().parents[5] / "fixtures" / "jats"


class OpenAccessDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_id: Literal["synthetic-publisher"] = SOURCE
    provider: Literal["europe-pmc"] = PROVIDER
    pmcid: str = Field(pattern=r"^PMC\d{3,10}$")
    source_url: str = Field(max_length=2048)
    canonical_url: str = Field(max_length=2048)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture: str = Field(pattern=r"^[a-z0-9-]{1,64}\.xml$")
    acquisition_mode: Literal["controlled_fixture"] = "controlled_fixture"

    @model_validator(mode="after")
    def bound(self) -> OpenAccessDocument:
        if self.source_url != f"{ORIGIN}/oa/{self.pmcid}.xml":
            raise ValueError("Registered synthetic article path required")
        if self.canonical_url != open_access_url(PmcIdentifier(value=self.pmcid)):
            raise ValueError("Europe PMC full-text provenance required")
        return self

    @property
    def identifier(self) -> PmcIdentifier:
        return PmcIdentifier(value=self.pmcid)


def _document(pmcid: str, digest: str, fixture: str) -> OpenAccessDocument:
    return OpenAccessDocument(
        pmcid=pmcid,
        source_url=f"{ORIGIN}/oa/{pmcid}.xml",
        canonical_url=open_access_url(PmcIdentifier(value=pmcid)),
        content_digest=digest,
        fixture=fixture,
    )


DOCUMENTS: tuple[OpenAccessDocument, ...] = (
    _document(
        "PMC10293847",
        "da8488e0c0e6ec9f55535e4a5761e7ab574ff3d6af3e76b5e6862c6f2da2c603",
        "plos-sample.xml",
    ),
    _document(
        "PMC1234567",
        "7e282973dddd8fa1d101ea66989d8873e0651e9ffe163ed9b905a8309b9ae4cf",
        "biomed-sample.xml",
    ),
    _document(
        "PMC887766",
        "aadc9fa4d5424086271e225e6fd64c3efda367505ed51edf41333d26fa7696be",
        "no-contact.xml",
    ),
    _document(
        "PMC7700001",
        "76a5fffb223ab16da05d29246c4f80f0def5cff431eecd2ee936d4c2a2fe575d",
        "usher-base-editing.xml",
    ),
)
BY_URL = {d.source_url: d for d in DOCUMENTS}
URLS = frozenset(BY_URL)


def registered(url: str) -> OpenAccessDocument | None:
    return BY_URL.get(url)


def fixture_bytes(document: OpenAccessDocument) -> bytes:
    """Read the committed synthetic bytes; any drift from the pinned digest refuses."""
    import hashlib

    if BY_URL.get(document.source_url) != document:
        raise FetchDenied("open_access_document_unregistered")
    data = (FIXTURES / document.fixture).read_bytes()
    if hashlib.sha256(data).hexdigest() != document.content_digest:
        raise FetchDenied("open_access_fixture_digest_mismatch")
    return data


def catalog_entries() -> list[dict[str, str]]:
    """The exact JSON migration 0027 stores in ``source_catalog.support``."""
    return [
        d.model_dump(mode="json", exclude={"fixture", "acquisition_mode"})
        | {"acquisition_mode": d.acquisition_mode}
        for d in DOCUMENTS
    ]
