"""Digest-pinned authored article bytes only; no publisher or socket fallback."""

import hashlib
from pathlib import Path

from emailmonitor.fetching.safety import FetchDenied

DIGESTS: dict[str, str] = {
    "article-a.html": "33c3bddb62834da34acb300b7c0bd7bb4c8728fb57e5ece43b8fc4e81920c3f0",
    "article-b.html": "87cd02138f7cc3dfa921ccdf9b2a1613e21529c1c89c3f36fcf36fd0ba8530b1",
    "tooltip.html": "f5ef425b50becc43b78b5a94c120c698d2c11d3d394325112d02355a0c27a893",
    "no-contact.html": "e743113b240ab1e931df471a9a3d8bd0137fc89157d69803a9238de3c8985b01",
}


def article_bytes(name: str) -> bytes:
    if name not in DIGESTS:
        raise FetchDenied("article_fixture_unavailable")
    path = Path(__file__).resolve().parents[5] / "fixtures/html" / name
    if path.is_symlink() or path.stat().st_size > 32768:
        raise FetchDenied("article_fixture_changed")
    with path.open("rb") as source:
        value = source.read(32769)
    if len(value) > 32768 or hashlib.sha256(value).hexdigest() != DIGESTS[name]:
        raise FetchDenied("article_fixture_changed")
    return value


# Authored tooltip plus fixed hostile diagnostic controls, before DOM interaction.
BROWSER_ACQUISITION_DIGEST = "7c26b49fe73a02899f77c88ebea70abb1f256399b66ed9c3b41eab12b587f9e3"
