"""Owned immutable service parser; legacy private parser channel stays unchanged."""

import json
import time

from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import XmlObservation
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing.xml_channel import (
    COMMAND,
    PROFILE,
    decode_output,
    exchange,
    verify_profile,
)
from emailmonitor.parsing.xml_protocol import XmlExpectation, encode_input


def _docker(*args: str, timeout: float = 15) -> bytes:
    try:
        output = exchange(["docker", *args], b"", timeout=timeout)
    except Exception:
        raise IsolationUnavailable("xml_container_control_failed") from None
    if len(output) > 65536:
        raise IsolationUnavailable("xml_container_control_failed")
    return output


def parse_pinned(
    settings: Settings,
    data: bytes,
    *,
    expected: XmlExpectation,
    image_id: str,
) -> XmlObservation:
    """Supervisor-only parser transport; immutable artifact, never a worker selector.

    The service worker receives a byte capability, not this host controller.
    Its supervisor supplies a separately verified installed parser image identity.
    The legacy diagnostic/private one-file entrypoints above are unchanged.
    """
    import re
    import secrets
    import sys

    require_fixture(settings)
    if type(image_id) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise IsolationUnavailable("xml_image_identity_invalid")
    framed = encode_input(data, expected)
    # One absolute controller budget, not fresh per-command wall ceilings. The
    # cleanup reserve remains available after work expiry; each subprocess also
    # has its existing bounded failure kill/reap. Legacy paths are unchanged.
    started = time.monotonic()
    deadline = started + 90
    cleanup_deadline = started + 135

    def control(*arguments: str) -> bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IsolationUnavailable("xml_parser_controller_timeout")
        return _docker(*arguments, timeout=min(15, remaining))

    image = json.loads(control("image", "inspect", image_id))
    if not isinstance(image, list) or len(image) != 1 or image[0].get("Id") != image_id:
        raise IsolationUnavailable("xml_image_identity_mismatch")
    owner = secrets.token_hex(16)
    name = "emailmonitor-service-xml-" + owner
    label = "io.emailmonitor.controlled-parser-owner"
    identifier: str | None = None
    attempted = False
    try:
        # Register an owned unique name before create, including uncertain output.
        attempted = True
        identifier = (
            control(
                "create",
                "--pull=never",
                "--interactive",
                "--name=" + name,
                "--label=" + label + "=" + owner,
                *PROFILE,
                image_id,
                *COMMAND,
            )
            .decode("ascii")
            .strip()
        )
        if re.fullmatch(r"[0-9a-f]{64}", identifier) is None:
            raise IsolationUnavailable("xml_container_identity_invalid")
        metadata = json.loads(control("inspect", identifier))[0]
        if (
            metadata.get("Id") != identifier
            or metadata.get("Name") != "/" + name
            or metadata.get("Image") != image_id
            or metadata.get("Config", {}).get("Labels", {}).get(label) != owner
        ):
            raise IsolationUnavailable("xml_container_identity_mismatch")
        verify_profile(metadata)
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
        if (
            not isinstance(environment, list)
            or any(
                not isinstance(v, str) or "=" not in v or v.split("=", 1)[0] not in allowed
                for v in environment
            )
            or len({v.split("=", 1)[0] for v in environment}) != len(environment)
            or environment.count("EM_ISOLATION_DIAGNOSTIC=synthetic-test-only") != 1
        ):
            raise IsolationUnavailable("xml_container_environment_invalid")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IsolationUnavailable("xml_parser_controller_timeout")
        output = exchange(
            ["docker", "start", "--attach", "--interactive", identifier],
            framed,
            timeout=min(30, remaining),
        )
        final = json.loads(control("inspect", identifier))[0]
        if final.get("Id") != identifier or final.get("Image") != image_id:
            raise IsolationUnavailable("xml_container_identity_mismatch")
        state = final["State"]
        if (
            state.get("Running") is not False
            or state.get("ExitCode") != 0
            or state.get("OOMKilled") is not False
        ):
            raise IsolationUnavailable("xml_parser_exit_invalid")
        return decode_output(output, data, expected)
    finally:
        if attempted:
            deadline = cleanup_deadline
            primary = sys.exception()
            try:
                # Only inspect the pre-registered exact name. A conflicting owner
                # is never removed, even when create returned uncertain output.
                owned = json.loads(control("inspect", name))[0]
                current = owned.get("Id")
                if (
                    not isinstance(current, str)
                    or re.fullmatch(r"[0-9a-f]{64}", current) is None
                    or (
                        identifier is not None
                        and re.fullmatch(r"[0-9a-f]{64}", identifier)
                        and current != identifier
                    )
                    or owned.get("Name") != "/" + name
                    or owned.get("Image") != image_id
                    or owned.get("Config", {}).get("Labels", {}).get(label) != owner
                ):
                    raise IsolationUnavailable("xml_parser_cleanup_identity_invalid")
                control("rm", "--force", current)
                if control(
                    "ps", "--all", "--quiet", "--no-trunc", "--filter", "id=" + current
                ).strip():
                    raise IsolationUnavailable("xml_parser_cleanup_failed")
            except BaseException:
                if primary is None:
                    raise IsolationUnavailable("xml_parser_cleanup_failed") from None
                BaseException.add_note(primary, "Owned XML parser cleanup failed")
