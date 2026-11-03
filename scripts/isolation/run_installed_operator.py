"""Installed-API browser launcher using the unchanged approved UI guest profile."""

import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from guest_outcome import guest_failure, guest_stage, observed_guest
from operator_ui_protocol import RequestFrame
from run_operator_ui_acceptance import conversation, validate_guest
from transport_topology import OWNER_LABEL, docker, remove_owned, require_owner, resource


@observed_guest
def run_installed(
    app: FastAPI,
    setup: dict[str, object],
    control: Callable[[str], None],
    before_reply: Callable[[RequestFrame], bool],
) -> dict[str, Any]:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true"
    ):
        raise RuntimeError("Reviewed disposable CI only; no local browser execution")
    root = Path(__file__).resolve().parents[2]
    owner = secrets.token_hex(16)
    image_name, container_name = "emailmonitor-ui-" + owner, "emailmonitor-ui-guest-" + owner
    profile = root / "scripts/isolation/seccomp-browser.json"
    # Register unique names before daemon actions, allowing owned-only ambiguous-outcome cleanup.
    try:
        guest_stage("build")
        docker(
            "build",
            "--platform=linux/amd64",
            "--label",
            OWNER_LABEL + "=" + owner,
            "--file",
            str(root / "scripts/isolation/Dockerfile.installed-operator-ui"),
            "--tag",
            image_name,
            str(root),
            timeout=600,
        )
        image = resource("image", image_name)
        if image is None:
            raise RuntimeError("Owned UI image missing")
        require_owner("image", image, owner)
        image_id = str(image["Id"])
        guest_stage("create")
        docker(
            "create",
            "--name",
            container_name,
            "--label",
            OWNER_LABEL + "=" + owner,
            "--interactive",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--security-opt=seccomp=" + str(profile),
            "--read-only",
            "--user=1000:1000",
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=1.0",
            "--pids-limit=128",
            "--ulimit=nofile=256:256",
            "--ulimit=core=0:0",
            "--shm-size=128m",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
            "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-operator-ui",
            "--env=HOME=/tmp/browser-home",
            "--env=XDG_CONFIG_HOME=/tmp/browser-config",
            "--env=CHROME_CONFIG_HOME=/tmp/browser-config",
            "--env=XDG_CACHE_HOME=/tmp/browser-cache",
            image_id,
            "python",
            "/app/operator_ui_acceptance.py",
        )
        guest_stage("initial_validation")
        guest = resource("container", container_name)
        if guest is None:
            raise RuntimeError("Owned UI guest missing")
        validate_guest(guest, image_id, owner, profile)
        guest_stage("conversation")
        result = conversation(container_name, app, setup, control, before_reply)
        guest_stage("final_validation")
        guest = resource("container", container_name)
        if guest is None:
            raise RuntimeError("Final guest state missing")
        validate_guest(guest, image_id, owner, profile)
        if (
            guest["State"]["Running"]
            or guest["State"]["OOMKilled"]
            or guest["State"]["ExitCode"] != 0
        ):
            raise RuntimeError("Actual UI guest did not stop cleanly")
        return result
    except BaseException:
        guest_failure()
        raise
    finally:
        cleanup_errors = []
        for kind, name in (("container", container_name), ("image", image_name)):
            try:
                guest_stage("cleanup_" + kind)
                remove_owned(kind, name, owner)
            except Exception as error:
                guest_failure(kind)
                cleanup_errors.append(type(error).__name__)
        if cleanup_errors:
            raise RuntimeError("Owned UI cleanup failed: " + ",".join(cleanup_errors))
        guest_stage("complete")
