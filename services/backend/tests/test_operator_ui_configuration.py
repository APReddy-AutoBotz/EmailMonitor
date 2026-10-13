"""Pure owned guest configuration refusal; no Docker or browser execution."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from emailmonitor.fetching.safety import FetchDenied
from run_operator_ui_acceptance import validate_guest
from transport_topology import OWNER_LABEL

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "scripts/isolation/seccomp-browser.json"


def guest() -> dict[str, Any]:
    return {
        "Image": "sha256:owned",
        "Config": {
            "Labels": {OWNER_LABEL: "owned"},
            "User": "1000:1000",
            "Volumes": None,
            "Cmd": ["python", "/app/operator_ui_acceptance.py"],
        },
        "Mounts": [],
        "NetworkSettings": {"Networks": {"none": {}}, "Ports": {}},
        "HostConfig": {
            "NetworkMode": "none",
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "ReadonlyRootfs": True,
            "Binds": None,
            "IpcMode": "private",
            "PidMode": "",
            "Memory": 536870912,
            "MemorySwap": 536870912,
            "PidsLimit": 128,
            "ShmSize": 134217728,
            "NanoCpus": 1000000000,
            "PortBindings": {},
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
            "SecurityOpt": [
                "no-new-privileges",
                "seccomp=" + json.dumps(json.loads(PROFILE.read_text())),
            ],
        },
    }


def test_only_original_owned_network_none_profile_is_admitted() -> None:
    validate_guest(guest(), "sha256:owned", "owned", PROFILE)


@pytest.mark.parametrize(
    "key,value",
    [
        ("NetworkMode", "host"),
        ("Privileged", True),
        ("Privileged", 0),
        ("CapAdd", ["SYS_ADMIN"]),
        ("CapDrop", []),
        ("ReadonlyRootfs", False),
        ("Binds", ["/unknown:/app"]),
        ("Memory", 0),
        ("MemorySwap", -1),
        ("PidsLimit", 0),
        ("NanoCpus", 0),
        ("PortBindings", {"443/tcp": [{}]}),
        ("Tmpfs", {"/tmp": "rw,exec"}),
        ("SecurityOpt", ["seccomp=unconfined"]),
    ],
)
def test_changed_security_resource_or_reachability_setting_refuses(key: str, value: object) -> None:
    document = guest()
    document["HostConfig"][key] = value
    with pytest.raises((RuntimeError, FetchDenied)):
        validate_guest(document, "sha256:owned", "owned", PROFILE)


@pytest.mark.parametrize("change", ["owner", "image", "user", "network", "mount", "command"])
def test_unknown_ownership_or_host_access_refuses(change: str) -> None:
    document = copy.deepcopy(guest())
    if change == "owner":
        document["Config"]["Labels"][OWNER_LABEL] = "unrelated"
    elif change == "image":
        document["Image"] = "sha256:unrelated"
    elif change == "user":
        document["Config"]["User"] = "0:0"
    elif change == "network":
        document["NetworkSettings"]["Networks"]["bridge"] = {}
    elif change == "mount":
        document["Mounts"] = [{"Type": "bind", "Source": "/unrelated"}]
    else:
        document["Config"]["Cmd"] = ["unknown"]
    with pytest.raises(RuntimeError):
        validate_guest(document, "sha256:owned", "owned", PROFILE)


def test_same_official_immutable_image_and_no_settings_or_secret_workflow() -> None:
    base = (ROOT / "scripts/isolation/Dockerfile.browser").read_text().splitlines()[1]
    assert base in (ROOT / "scripts/isolation/Dockerfile.operator-ui").read_text().splitlines()
    host = (ROOT / "scripts/isolation/run_operator_ui_acceptance.py").read_text()
    for forbidden in [
        "--privileged",
        "--cap-add",
        "--network=host",
        "--ipc=host",
        "sysctl",
        "iptables",
        "docker.sock",
        "--volume",
        "--mount",
    ]:
        assert forbidden not in host
    workflow = (ROOT / ".github/workflows/operator-ui.yml").read_text()
    assert "contents: read" in workflow and "persist-credentials: false" in workflow
    assert "pull_request_target" not in workflow and "secrets." not in workflow
    guest_code = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    assert "chromium_sandbox=True" in guest_code and 'service_workers="block"' in guest_code
    assert (
        ".click(" not in guest_code
        and ".fill(" not in guest_code
        and ".select_option(" not in guest_code
    )


def test_ordered_build_context_excludes_source_environment_and_unknown_asset_subtrees() -> None:
    import fnmatch

    rules = (ROOT / ".dockerignore").read_text().splitlines()

    def included(path: str) -> bool:
        admitted = True
        candidates = [path, *[str(parent) for parent in Path(path).parents if str(parent) != "."]]
        for raw in rules:
            admit = raw.startswith("!")
            pattern = raw.removeprefix("!").rstrip("/")

            def matches(candidate: str, pattern: str = pattern) -> bool:
                if pattern == "**":
                    return True
                if pattern.endswith("/**"):
                    return candidate.startswith(pattern[:-2])
                left, right = candidate.split("/"), pattern.split("/")
                return len(left) == len(right) and all(
                    fnmatch.fnmatchcase(a, b) for a, b in zip(left, right, strict=True)
                )

            if any(matches(candidate) for candidate in candidates):
                admitted = admit
        return admitted

    for name in [
        "apps/web/dist/index.html",
        "apps/web/dist/assets/index-actual12.js",
        "apps/web/dist/assets/index-actual12.css",
        "scripts/isolation/operator_ui_acceptance.py",
        "scripts/isolation/operator_ui_protocol.py",
    ]:
        assert included(name)
    for name in [
        "apps/web/src/App.tsx",
        "apps/web/.env",
        "apps/web/dist/.env",
        "apps/web/dist/assets/unknown.txt",
        "apps/other/dist/index.html",
        "services/backend/.venv/private.txt",
        "services/backend/.env",
        "services/other/private.txt",
        "scripts/unrelated/private.txt",
        "scripts/isolation/unrelated.txt",
    ]:
        assert not included(name)
