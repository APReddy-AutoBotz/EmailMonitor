"""Explicit test-only repository fixture composition, with immutable byte digests.

Only authored synthetic search bytes are parsed in this test assembly. Acquired
publisher bytes must go to the network-none worker; production has no assembly.
"""

import hashlib
from pathlib import Path
from uuid import UUID

from emailmonitor.discovery.search import parse_search
from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.fetching.fixture import (
    ByteResponse,
    FetchLimits,
    FixtureByteTransport,
    FixtureGateway,
    TenantFixtureAuthorization,
)
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.policy import Operation

DIGESTS = {
    "search-page-1.html": "2986a2ab4869826881786e1244369b4ccb248a7d7dde9a348c63b453903d2e51",
    "search-page-2.html": "559ff4965c0973f9c20abbb445d5dd2ee192d68ca83708f42eed6996e333e35f",
}


def fixture_bytes(name: str) -> bytes:
    if name not in DIGESTS:
        raise FetchDenied("discovery_fixture_unavailable")
    root = Path(__file__).resolve().parents[5] / "fixtures" / "html"
    path = root / name
    if path.is_symlink() or path.stat().st_size > 32768:
        raise FetchDenied("discovery_fixture_changed")
    with path.open("rb") as stream:
        payload = stream.read(32769)
    if len(payload) > 32768 or hashlib.sha256(payload).hexdigest() != DIGESTS[name]:
        raise FetchDenied("discovery_fixture_changed")
    return payload


def step_fixture(
    discovery: Discovery, org: UUID, job: UUID, expected_revision: int
) -> dict[str, object]:
    row = discovery.prepare(org, job)
    if row["revision"] != expected_revision:
        raise ValueError("Discovery revision conflict")
    state = DiscoveryState.model_validate(row["checkpoint"])
    if state.next_url is None:
        raise ValueError("Pending page required")
    name = state.next_url.rsplit("/", 1)[-1]
    payload = fixture_bytes(name)
    auth = TenantFixtureAuthorization(
        discovery.database,
        discovery.token,
        org,
        "synthetic-publisher",
        int(str(row["policy_version"])),
    )
    # Search authorization is checked during prepare and again during commit;
    # the same current HTML policy governs the authored byte-release gateway.
    transport = FixtureByteTransport(
        discovery.settings,
        {
            state.next_url: ByteResponse(200, (payload,), content_length=len(payload)),
        },
    )
    acquired = FixtureGateway(
        discovery.settings, transport, auth, FetchLimits(max_bytes=32768)
    ).fetch(
        state.next_url,
        Operation.HTML,
    )
    page = parse_search(discovery.settings, state.next_url, acquired)
    return discovery.commit(org, job, expected_revision, page)
