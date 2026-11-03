"""Test-only binding of actual parser metadata to the CI-owned curated image."""

import os
import re
from collections.abc import Mapping

LABEL = "io.emailmonitor.metadata-prerequisite-owner"


def require_packaged_image(metadata: Mapping[str, object]) -> None:
    marker = os.environ.get("EM_REQUIRE_XML_INTEGRATION")
    identifier = os.environ.get("EM_EXPECTED_XML_IMAGE_ID")
    owner = os.environ.get("EM_EXPECTED_XML_IMAGE_OWNER")
    if marker is None and identifier is None and owner is None:
        return  # Existing standalone diagnostic acceptance remains supported.
    if (
        marker != "synthetic-test-only"
        or not isinstance(identifier, str)
        or re.fullmatch(r"sha256:[a-f0-9]{64}", identifier) is None
        or not isinstance(owner, str)
        or re.fullmatch(r"[a-f0-9]{32}", owner) is None
    ):
        raise AssertionError("xml_integration_identity_required")
    config = metadata.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if (
        metadata.get("Image") != identifier
        or not isinstance(labels, dict)
        or labels.get(LABEL) != owner
    ):
        raise AssertionError("xml_integration_identity_mismatch")
