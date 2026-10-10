"""Disposable CI-only container checks; never changes host security settings."""

import json
import os
import subprocess
from pathlib import Path

IMAGE = "emailmonitor-parser-diagnostic:local"


def docker(*arguments: str, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=True, timeout=timeout
    )


def run(command: list[str], *, expected_oom: bool = False) -> dict[str, object]:
    created = docker(
        "create",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--user=65532:65532",
        "--memory=128m",
        "--memory-swap=128m",
        "--cpus=0.5",
        "--pids-limit=32",
        "--ulimit=nofile=64:64",
        "--ulimit=core=0:0",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
        "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-test-only",
        IMAGE,
        *command,
    )
    identifier = created.stdout.strip()
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise RuntimeError("Unexpected disposable container identifier")
    try:
        metadata = json.loads(docker("inspect", identifier).stdout)[0]
        config = metadata["HostConfig"]
        if (
            config["NetworkMode"] != "none"
            or config["Privileged"]
            or config["CapAdd"]
            or config["CapDrop"] != ["ALL"]
            or config["SecurityOpt"] != ["no-new-privileges"]
            or not config["ReadonlyRootfs"]
            or config["Binds"]
            or config["Memory"] != 134217728
            or config["MemorySwap"] != 134217728
            or config["PidsLimit"] != 32
            or config["NanoCpus"] != 500000000
        ):
            raise RuntimeError("Container isolation/resource configuration mismatch")
        # No Docker/host socket, credential, control-plane or writable host mounts.
        started = subprocess.run(
            ["docker", "start", "--attach", identifier],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        after = json.loads(docker("inspect", identifier).stdout)[0]["State"]
        if expected_oom:
            if not after["OOMKilled"] or after["ExitCode"] != 137:
                raise RuntimeError("Actual memory enforcement not established")
        elif started.returncode or after["ExitCode"] or after["OOMKilled"]:
            raise RuntimeError("Parser diagnostic failed: " + started.stderr[:300])
        else:
            evidence = json.loads(started.stdout)
            if evidence["diagnostic"] != "network-none-parser":
                raise RuntimeError("Missing actual parser evidence")
            print(json.dumps(evidence))
        return {"oom_killed": after["OOMKilled"], "exit_code": after["ExitCode"]}
    finally:
        docker("rm", "--force", identifier)


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Reviewed disposable CI environment required")
    root = Path(__file__).resolve().parents[2]
    docker(
        "build",
        "--file",
        str(root / "scripts/isolation/Dockerfile.parser"),
        "--tag",
        IMAGE,
        str(root),
        timeout=600,
    )
    run(["python", "/app/parser_acceptance.py"])
    # Ordinary synthetic memory exhaustion proves the configured limit actually
    # terminates just this disposable process. No host limit/security is changed.
    evidence = run(
        ["python", "-c", "chunks=[]\nwhile True: chunks.append(bytearray(8 * 1024 * 1024))"],
        expected_oom=True,
    )
    print(json.dumps({"diagnostic": "parser-memory-limit", **evidence}))


if __name__ == "__main__":
    main()
