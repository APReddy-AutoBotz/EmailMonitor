"""Trusted host channel for the JATS sandbox command (OA-029).

Reuses the reviewed XML parser image, isolation profile, bounded pipe and Docker
control helpers from ``xml_channel`` without modifying that pinned module. Only
the command differs; every container property is verified exactly as for XML.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping

from emailmonitor.config import Settings
from emailmonitor.extraction.jats import JatsObservation
from emailmonitor.extraction.xml_retained import MAX_ENVELOPE
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing import xml_channel
from emailmonitor.parsing.jats_protocol import JatsExpectation, encode_input

JATS_COMMAND = ("python", "-m", "emailmonitor.parsing.jats_worker")


def verify_profile(metadata: Mapping[str, object]) -> None:
    """Exact JATS command, then every XML sandbox property via the reviewed check."""
    config = metadata.get("Config")
    if not isinstance(config, dict) or config.get("Cmd") != list(JATS_COMMAND):
        raise ValueError("Registered JATS parser command required")
    shadow = copy.deepcopy(dict(metadata))
    shadow_config = shadow["Config"]
    assert isinstance(shadow_config, dict)
    shadow_config["Cmd"] = list(xml_channel.COMMAND)
    xml_channel.verify_profile(shadow, private_offline=False)


def decode_output(output: bytes, data: bytes, expected: JatsExpectation) -> JatsObservation:
    expected = JatsExpectation.model_validate(expected.model_dump())
    expected.check_bytes(data)
    if not output or len(output) > MAX_ENVELOPE:
        raise ValueError("Bounded parser output required")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate parser field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("Invalid parser number")

    text = output.decode("utf-8")
    document, end = json.JSONDecoder(object_pairs_hook=pairs, parse_constant=constant).raw_decode(
        text
    )
    if text[end:] != "\n" or not isinstance(document, dict):
        raise ValueError("Exact parser envelope required")
    if (
        set(document) != {"profile", "observation"}
        or document["profile"] != "network-none-parser-v1"
    ):
        raise ValueError("Registered parser profile required")
    observed = JatsObservation.model_validate(document["observation"])
    expected.check_observation(observed)
    return observed


def parse_isolated(settings: Settings, data: bytes, expected: JatsExpectation) -> JatsObservation:
    require_fixture(settings)
    framed = encode_input(data, expected)
    image_metadata = json.loads(xml_channel._docker("image", "inspect", xml_channel.IMAGE))[0]
    image_id = image_metadata.get("Id", "")
    if (
        not isinstance(image_id, str)
        or len(image_id) != 71
        or not image_id.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in image_id[7:])
    ):
        raise IsolationUnavailable("jats_image_identity_invalid")
    identifier = (
        xml_channel._docker(
            "create", "--pull=never", "--interactive", *xml_channel.PROFILE, image_id, *JATS_COMMAND
        )
        .decode()
        .strip()
    )
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise IsolationUnavailable("jats_container_identity_invalid")
    try:
        metadata = json.loads(xml_channel._docker("inspect", identifier))[0]
        verify_profile(metadata)
        if metadata.get("Image") != image_id:
            raise IsolationUnavailable("jats_image_identity_mismatch")
        environment = metadata["Config"].get("Env", [])
        allowed = {
            "PATH",
            "LANG",
            "GPG_KEY",
            "PYTHON_VERSION",
            "PYTHON_SHA256",
            "PYTHONPATH",
            "PYTHONDONTWRITEBYTECODE",
            "EM_ISOLATION_DIAGNOSTIC",
        }
        if not isinstance(environment, list) or any(
            not isinstance(value, str) or value.split("=", 1)[0] not in allowed
            for value in environment
        ):
            raise IsolationUnavailable("jats_container_environment_invalid")
        output = xml_channel.exchange(
            ["docker", "start", "--attach", "--interactive", identifier], framed
        )
        state = json.loads(xml_channel._docker("inspect", identifier))[0]["State"]
        if (
            state.get("Running") is not False
            or state.get("ExitCode") != 0
            or state.get("OOMKilled") is not False
        ):
            raise IsolationUnavailable("jats_parser_exit_invalid")
        try:
            return decode_output(output, data, expected)
        except (ValueError, TypeError, KeyError):
            raise IsolationUnavailable("jats_parser_output_invalid") from None
    finally:
        xml_channel._docker("rm", "--force", identifier)
