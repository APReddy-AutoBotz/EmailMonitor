"""Source-bound isolated XML parsing, deliberately separate from synthetic storage.

This host composition can be exercised with controlled bytes in explicit test mode.
It does not fetch anything, enable provider policy, or grant retention/export rights.
"""

from dataclasses import dataclass, field
from typing import Literal

from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import XmlObservation
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.fetching.sciencedirect import AcquiredResponse, ProviderBoundary
from emailmonitor.parsing.xml_channel import parse_isolated
from emailmonitor.parsing.xml_protocol import XmlExpectation


@dataclass(frozen=True)
class BoundXmlObservation:
    acquisition: AcquiredResponse = field(repr=False)
    observation: XmlObservation = field(repr=False)


def parse_response(
    settings: Settings,
    boundary: ProviderBoundary,
    acquired: AcquiredResponse,
    *,
    profile: Literal["article_retrieval_response", "xocs_document"],
) -> BoundXmlObservation:
    boundary.require_response(acquired)
    identifier = acquired.request.article
    if identifier is None:
        raise FetchDenied("provider_route_denied")
    expected = XmlExpectation(
        requested_identifier=identifier,
        content_digest=acquired.content_digest,
        source_profile=profile,
    )
    observed = parse_isolated(settings, acquired.body, expected=expected)
    # Reject a compromised/misbound child before any host record is released.
    observed = XmlObservation.model_validate(observed.model_dump())
    expected.check_observation(observed)
    boundary.require_response(acquired)
    return BoundXmlObservation(acquired, observed)
