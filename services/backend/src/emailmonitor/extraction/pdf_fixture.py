"""Pinned authored bytes only; no PDF acquisition or publisher fallback."""

import hashlib
from pathlib import Path
from types import MappingProxyType

from emailmonitor.fetching.safety import FetchDenied

DIGESTS = MappingProxyType(
    {
        "ambiguous.pdf": "7ff5d5fe802aa77b1ce845f9ebb2fcfbe98e556f96836716045e949ee7645306",
        "article-a.pdf": "a216f8bde348256ee912f592956dfc66ea83b106e2f4c05b3c6a28f5e6cfd9cc",
        "article-b.pdf": "e24a7228b39e04c6f56203317ef90300c6a8b622b16f3672c8cc83784d0d0b8a",
        "corrupt.pdf": "bfdd8c6384be76b5ab1ed6f2aa9a2a3fdcb49c8f62ffda3bdcb85091bc14b111",
        "encrypted.pdf": "4e253514d7bb1007937cc7456821c9b5393a275e748658847208590029e4b18e",
        "no-contact.pdf": "3db38695a632f805b3b56571f12c133bbd80c56d4cddcbc812a025876e8e1d59",
        "page-cap.pdf": "8e64ad429519fe6f45c17902e032e57f4d0568f3809475bb350f6f532878cb59",
        "scanned.pdf": "a1c762aad46bd8f0eda32a51dee4d8026ac7800c38b4e1f04578d5d9ee98d089",
        "wrapped.pdf": "ee5449815873cca0eca7e919b340d0598b1863f4bf439a9b4eef14fae6b893fb",
    }
)


def pdf_bytes(name: str) -> bytes:
    if name not in DIGESTS:
        raise FetchDenied("pdf_fixture_unavailable")
    path = Path(__file__).resolve().parents[5] / "fixtures/pdf" / name
    if path.is_symlink() or path.stat().st_size > 262144:
        raise FetchDenied("pdf_fixture_changed")
    with path.open("rb") as source:
        data = source.read(262145)
    if len(data) > 262144 or hashlib.sha256(data).hexdigest() != DIGESTS[name]:
        raise FetchDenied("pdf_fixture_changed")
    return data
