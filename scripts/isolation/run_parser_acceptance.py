"""Disposable CI-only container checks; never changes host security settings."""

import json
import os
import subprocess
import time
from pathlib import Path

IMAGE = "emailmonitor-parser-diagnostic:local"


class MemoryProofRefused(RuntimeError):
    """Fixed diagnostic category; never a substitute for required OOM evidence."""

    def __init__(self, message: str, category: str) -> None:
        super().__init__(message)
        self.category = category


def docker(*arguments: str, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *arguments], capture_output=True, text=True, check=True, timeout=timeout
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "Parser Docker command failed: "
            + json.dumps(
                {
                    "operation": arguments[0] if arguments else "unknown",
                    "returncode": error.returncode,
                    "stdout": (error.stdout or "")[-4096:],
                    "stderr": (error.stderr or "")[-4096:],
                }
            )
        ) from error


def settled_oom(identifier: str, state: dict[str, object]) -> dict[str, object]:
    """Observe the separately delivered daemon OOM event for at most two seconds."""
    observations = []
    deadline = time.monotonic() + 2
    for observation in range(11):
        observations.append({key: state.get(key) for key in ("Running", "OOMKilled", "ExitCode")})
        if (
            state.get("Running") is False
            and state.get("OOMKilled") is True
            and state.get("ExitCode") == 137
        ):
            break
        if observation == 10 or time.monotonic() >= deadline:
            break
        time.sleep(0.2)
        state = json.loads(docker("inspect", identifier, timeout=2).stdout)[0]["State"]
    print(json.dumps({"parser_oom_state_observations": observations}), flush=True)
    return state


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
            after = settled_oom(identifier, after)
            if (
                after.get("Running") is not False
                or after["OOMKilled"] is not True
                or after["ExitCode"] != 137
            ):
                raise MemoryProofRefused(
                    "Actual memory enforcement not established: "
                    + json.dumps(
                        {
                            "oom_killed": after["OOMKilled"],
                            "exit_code": after["ExitCode"],
                            "engine_error": str(after.get("Error", ""))[:1024],
                            "stderr": started.stderr[:1024],
                        }
                    ),
                    "oom_flag_absent_exit137"
                    if after.get("Running") is False
                    and after.get("OOMKilled") is False
                    and after.get("ExitCode") == 137
                    else "other_refusal",
                )
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
    phase = "build"
    memory = "not_verified"
    try:
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
        phase = "extraction"
        run(["python", "/app/parser_acceptance.py"])
        # Ordinary synthetic memory exhaustion proves the configured limit actually
        # terminates just this disposable process. No host limit/security is changed.
        phase = "memory"
        evidence = run(
            ["python", "-c", "chunks=[]\nwhile True: chunks.append(bytearray(8 * 1024 * 1024))"],
            expected_oom=True,
        )
        memory = "verified"
        print(json.dumps({"diagnostic": "parser-memory-limit", **evidence}))
        phase = "complete"
    except MemoryProofRefused as error:
        memory = (
            error.category
            if error.category in {"oom_flag_absent_exit137", "other_refusal"}
            else "other_refusal"
        )
        raise
    finally:
        # Fixed categories only; never exception text, environment or parser data.
        # The original run/cleanup exception still determines the job result.
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            try:
                with Path(output).open("a") as stream:
                    stream.write("phase=" + phase + "\nmemory=" + memory + "\n")
            except OSError:
                print("Parser phase receipt unavailable", flush=True)


if __name__ == "__main__":
    main()
