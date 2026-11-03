"""The CI-only image expectation cannot silently accept another parser artifact."""

import pytest
from xml_image_evidence import LABEL, require_packaged_image

IMAGE = "sha256:" + "a" * 64
OWNER = "b" * 32
KEYS = ("EM_REQUIRE_XML_INTEGRATION", "EM_EXPECTED_XML_IMAGE_ID", "EM_EXPECTED_XML_IMAGE_OWNER")


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_standalone_diagnostic_remains_supported(clean_environment: None) -> None:
    require_packaged_image({})


def test_actual_image_and_owner_match(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in zip(KEYS, ("synthetic-test-only", IMAGE, OWNER), strict=True):
        monkeypatch.setenv(key, value)
    require_packaged_image({"Image": IMAGE, "Config": {"Labels": {LABEL: OWNER}}})


@pytest.mark.parametrize("missing", KEYS)
def test_missing_proof_cannot_disable_assertion(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for key, value in zip(KEYS, ("synthetic-test-only", IMAGE, OWNER), strict=True):
        if key != missing:
            monkeypatch.setenv(key, value)
    with pytest.raises(AssertionError, match="^xml_integration_identity_required$"):
        require_packaged_image({"Image": IMAGE, "Config": {"Labels": {LABEL: OWNER}}})


@pytest.mark.parametrize(
    "index,value", [(0, "true"), (1, "sha256:bad"), (1, "sha256:" + "A" * 64), (2, "bad")]
)
def test_malformed_proof_refused(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch, index: int, value: str
) -> None:
    values = ["synthetic-test-only", IMAGE, OWNER]
    values[index] = value
    for key, item in zip(KEYS, values, strict=True):
        monkeypatch.setenv(key, item)
    with pytest.raises(AssertionError, match="^xml_integration_identity_required$"):
        require_packaged_image({})


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"Image": IMAGE},
        {"Image": IMAGE, "Config": None},
        {"Image": IMAGE, "Config": {"Labels": {}}},
        {"Image": IMAGE, "Config": {"Labels": {LABEL: "c" * 32}}},
        {"Image": "sha256:" + "c" * 64, "Config": {"Labels": {LABEL: OWNER}}},
    ],
)
def test_wrong_observed_image_or_owner_refused(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, object]
) -> None:
    for key, value in zip(KEYS, ("synthetic-test-only", IMAGE, OWNER), strict=True):
        monkeypatch.setenv(key, value)
    with pytest.raises(AssertionError, match="^xml_integration_identity_mismatch$"):
        require_packaged_image(metadata)
