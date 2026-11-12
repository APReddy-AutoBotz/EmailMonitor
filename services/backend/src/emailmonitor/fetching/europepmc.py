"""Europe PMC REST API boundary and full-text JATS XML gateway.

Consumes responses supplied by the protected transport; enforces host/path bounds,
SHA-256 digest integrity, size ceilings, and binds observed JATS XML records.
"""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.extraction.jats import JatsObservation, parse_jats_xml
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import PmcIdentifier
from emailmonitor.sources.policy import Operation

EUROPE_PMC_SOURCE = "europe_pmc_v1"
HOSTS = frozenset({"www.ebi.ac.uk"})
API_ORIGIN: Literal["https://www.ebi.ac.uk"] = "https://www.ebi.ac.uk"
MAX_BYTES = 4_194_304  # 4 MB
FIXTURES_JATS = Path(__file__).resolve().parents[5] / "fixtures" / "jats"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EuropePmcRequest(Contract):
    pmcid: PmcIdentifier

    @property
    def path(self) -> str:
        return f"/europepmc/webservices/rest/{self.pmcid.value}/fullTextXML"

    @property
    def url(self) -> str:
        return f"{API_ORIGIN}{self.path}"

    @property
    def operation(self) -> Operation:
        return Operation.XML

    @property
    def max_bytes(self) -> int:
        return MAX_BYTES


class EuropePmcResponse(Contract):
    request: EuropePmcRequest
    status_code: int = Field(ge=200, le=599)
    media_type: str = "text/xml"
    body: bytes
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    elapsed_ms: int = Field(ge=0, le=300_000)

    @model_validator(mode="after")
    def verify_response(self) -> "EuropePmcResponse":
        if len(self.body) > MAX_BYTES:
            raise FetchDenied("europe_pmc_payload_too_large")
        actual_digest = hashlib.sha256(self.body).hexdigest()
        if self.content_digest != actual_digest:
            raise FetchDenied("content_digest_mismatch")
        return self


class EuropePmcBoundary:
    """Validates Europe PMC responses and bridges to JATS XML parsing."""

    def require_response(self, response: EuropePmcResponse) -> None:
        if response.status_code != 200:
            raise FetchDenied(f"europe_pmc_http_{response.status_code}")
        if "xml" not in response.media_type.lower():
            raise FetchDenied("invalid_media_type_not_xml")

    def parse(self, response: EuropePmcResponse) -> JatsObservation:
        self.require_response(response)
        return parse_jats_xml(response.body, response.request.pmcid)


class EuropePmcFixtureGateway:
    """Offline test gateway resolving registered PMC fixtures without live egress."""

    _FIXTURE_MAP = {
        "PMC10293847": "plos-sample.xml",
        "PMC1234567": "biomed-sample.xml",
        "PMC887766": "no-contact.xml",
    }

    def fetch(self, request: EuropePmcRequest) -> EuropePmcResponse:
        pmcid = request.pmcid.value
        filename = self._FIXTURE_MAP.get(pmcid)
        if not filename:
            raise FetchDenied("unregistered_pmc_fixture")

        fixture_file = FIXTURES_JATS / filename
        if not fixture_file.is_file():
            raise FetchDenied("missing_fixture_file")

        data = fixture_file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()

        return EuropePmcResponse(
            request=request,
            status_code=200,
            media_type="text/xml",
            body=data,
            content_digest=digest,
            elapsed_ms=15,
        )
