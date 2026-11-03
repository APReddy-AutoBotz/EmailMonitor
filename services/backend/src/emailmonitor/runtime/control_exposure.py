"""Read-only CI host prerequisite, not a daemon reconfiguration or egress proof.

The trusted supervisor must not configure a proxy to Docker or change listeners
while its worker runs. A host-network service worker is not network isolated.
Missing privileged listener ownership evidence is a refusal, never an assumption.
"""

import json
import os
import re
from pathlib import Path

from emailmonitor.parsing.xml_channel import exchange


class ControlExposureRefused(RuntimeError):
    pass


def read_control(command: list[str]) -> bytes:
    # Existing concurrent bounded stdout/stderr reader, including five-second
    # process termination/reap on failure. No raw output enters diagnostics.
    try:
        result = exchange(command, b"", timeout=5)
        if len(result) > 65536:
            raise ValueError
        return result
    except Exception:
        raise ControlExposureRefused("service_control_exposure_unverified") from None


def require_local_control_only() -> None:
    """Prove current local Unix endpoint ownership and absence of dockerd TCP.

    sudo is a fixed read-only listener inspection, never an arbitrary command.
    Existing root supervisors read directly; unprivileged ss is never evidence.
    """
    try:
        if any(value for name, value in os.environ.items() if name.startswith("DOCKER_")):
            raise ValueError
        raw = read_control(
            ["docker", "context", "inspect", "--format={{json .Endpoints.docker.Host}}"]
        )
        endpoint = json.loads(raw)
        if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
            raise ValueError
        path = Path(endpoint.removeprefix("unix://"))
        if path.resolve(strict=True) != Path("/run/docker.sock") or not path.is_socket():
            raise ValueError
        prefix = [] if os.geteuid() == 0 else ["/usr/bin/sudo", "-n"]
        tcp = read_control([*prefix, "/usr/bin/ss", "-H", "-ltnp"]).decode("ascii")
        unix = read_control([*prefix, "/usr/bin/ss", "-H", "-lxnp"]).decode("ascii")

        # Inspect every dockerd TCP listener, regardless of address/port. Fixed
        # ASCII grammar prevents matching a peer's path as an owner declaration.
        def owners(line: str) -> list[tuple[str, str]]:
            return re.findall(r'\("([^"\\]+)",pid=([1-9][0-9]*),fd=[0-9]+\)', line)

        if any(not owners(line) for line in tcp.splitlines()) or any(
            name == "dockerd" for line in tcp.splitlines() for name, _ in owners(line)
        ):
            raise ValueError
        candidates = [
            line
            for line in unix.splitlines()
            if re.search(r"(?:^|\s)/(?:var/)?run/docker\.sock(?:\s|$)", line)
        ]
        if len(candidates) != 1:
            raise ValueError
        line = candidates[0]
        processes = owners(line)
        if (
            line.split()[:2] != ["u_str", "LISTEN"]
            or not processes
            or not any(name == "dockerd" for name, _ in processes)
            or any(name not in {"dockerd", "systemd"} for name, _ in processes)
            or len({pid for _, pid in processes}) != len(processes)
        ):
            raise ValueError
    except Exception:
        raise ControlExposureRefused("service_control_exposure_unverified") from None
