"""Tests for Europe PMC gateway, response boundary, and JATS XML bridge."""

import hashlib

import pytest

from emailmonitor.fetching.europepmc import (
    EuropePmcBoundary,
    EuropePmcFixtureGateway,
    EuropePmcRequest,
    EuropePmcResponse,
)
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import PmcIdentifier


def test_europepmc_request_planning():
    req = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    assert req.path == "/europepmc/webservices/rest/PMC10293847/fullTextXML"
    assert req.url == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10293847/fullTextXML"
    assert req.max_bytes == 4_194_304
    assert req.operation == "fetch_xml"


def test_europepmc_fixture_gateway_fetch():
    gateway = EuropePmcFixtureGateway()
    boundary = EuropePmcBoundary()

    req = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    res = gateway.fetch(req)

    assert res.status_code == 200
    assert res.media_type == "text/xml"
    assert len(res.body) > 0

    obs = boundary.parse(res)
    assert obs.status == "observed"
    assert obs.title == "Advances in CRISPR-Cas9 Target Specificity"
    assert obs.journal == "PLOS Biology"
    assert len(obs.authors) == 2
    assert len(obs.candidates) == 1
    assert obs.candidates[0].raw_address == "marcus.vance@biotech.ethz.ch"


def test_unregistered_pmc_fixture_denial():
    gateway = EuropePmcFixtureGateway()
    req = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC9999999"))
    with pytest.raises(FetchDenied, match="unregistered_pmc_fixture"):
        gateway.fetch(req)


def test_digest_mismatch_denial():
    req = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    with pytest.raises(FetchDenied, match="content_digest_mismatch"):
        EuropePmcResponse(
            request=req,
            status_code=200,
            body=b"<article/>",
            content_digest="0" * 64,  # Incorrect hash!
            elapsed_ms=10,
        )


def test_payload_too_large_denial():
    req = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    huge_body = b"<article>" + (b" " * (4 * 1024 * 1024 + 50)) + b"</article>"
    digest = hashlib.sha256(huge_body).hexdigest()

    with pytest.raises(FetchDenied, match="europe_pmc_payload_too_large"):
        EuropePmcResponse(
            request=req,
            status_code=200,
            body=huge_body,
            content_digest=digest,
            elapsed_ms=10,
        )


def test_non_200_status_denial():
    req = EuropePmcRequest(pmcid=PmcIdentifier(value="PMC10293847"))
    body = b"<article/>"
    digest = hashlib.sha256(body).hexdigest()
    res = EuropePmcResponse(
        request=req,
        status_code=404,
        body=body,
        content_digest=digest,
        elapsed_ms=10,
    )
    boundary = EuropePmcBoundary()
    with pytest.raises(FetchDenied, match="europe_pmc_http_404"):
        boundary.parse(res)
