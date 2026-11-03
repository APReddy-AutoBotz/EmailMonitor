"""Disposable CI-only container checks; never changes host security settings."""

import json
import os
import subprocess
import time
from pathlib import Path

IMAGE = "emailmonitor-parser-diagnostic:local"


def report_oom(key: str, value: str) -> None:
    """Report only closed, value-free diagnostic categories to the owned CI step."""
    allowed = {
        "parser_oom_phase": {
            "create",
            "identifier",
            "config_inspect",
            "config_check",
            "attach",
            "state_inspect",
            "settle",
            "verify",
            "complete",
        },
        "parser_oom_cleanup": {"started", "complete"},
    }
    if key not in allowed or value not in allowed[key]:
        return
    output = os.environ.get("GITHUB_OUTPUT")
    if os.environ.get("EM_PARSER_STAGE_REPORT") != "true" or not output:
        return
    try:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(key + "=" + value + "\n")
    except OSError:
        pass


def report_oom_state(state: dict[str, object]) -> None:
    """Describe actual daemon fields without retaining arbitrary values."""
    running = state.get("Running")
    killed = state.get("OOMKilled")
    code = state.get("ExitCode")
    stopped = "stopped" if running is False else "running" if running is True else "unknown"
    oom = "killed" if killed is True else "notkilled" if killed is False else "unknown"
    exit_code = (
        "137" if type(code) is int and code == 137 else "other" if type(code) is int else "unknown"
    )
    output = os.environ.get("GITHUB_OUTPUT")
    if os.environ.get("EM_PARSER_STAGE_REPORT") != "true" or not output:
        return
    try:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write("parser_oom_state=" + stopped + "_" + oom + "_" + exit_code + "\n")
    except OSError:
        pass


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
    if expected_oom:
        report_oom("parser_oom_phase", "create")
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
    if expected_oom:
        report_oom("parser_oom_phase", "identifier")
    identifier = created.stdout.strip()
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise RuntimeError("Unexpected disposable container identifier")
    try:
        if expected_oom:
            report_oom("parser_oom_phase", "config_inspect")
        metadata = json.loads(docker("inspect", identifier).stdout)[0]
        config = metadata["HostConfig"]
        if expected_oom:
            report_oom("parser_oom_phase", "config_check")
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
        if expected_oom:
            report_oom("parser_oom_phase", "attach")
        started = subprocess.run(
            ["docker", "start", "--attach", identifier],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if expected_oom:
            report_oom("parser_oom_phase", "state_inspect")
        after = json.loads(docker("inspect", identifier).stdout)[0]["State"]
        if expected_oom:
            report_oom("parser_oom_phase", "settle")
            after = settled_oom(identifier, after)
            report_oom("parser_oom_phase", "verify")
            report_oom_state(after)
            if (
                after.get("Running") is not False
                or after["OOMKilled"] is not True
                or after["ExitCode"] != 137
            ):
                raise RuntimeError(
                    "Actual memory enforcement not established: "
                    + json.dumps(
                        {
                            "oom_killed": after["OOMKilled"],
                            "exit_code": after["ExitCode"],
                            "engine_error": str(after.get("Error", ""))[:1024],
                            "stderr": started.stderr[:1024],
                        }
                    )
                )
        elif started.returncode or after["ExitCode"] or after["OOMKilled"]:
            raise RuntimeError("Parser diagnostic failed: " + started.stderr[:300])
        else:
            evidence = json.loads(started.stdout)
            if evidence["diagnostic"] != "network-none-parser":
                raise RuntimeError("Missing actual parser evidence")
            print(json.dumps(evidence))
        if expected_oom:
            report_oom("parser_oom_phase", "complete")
        return {"oom_killed": after["OOMKilled"], "exit_code": after["ExitCode"]}
    finally:
        if expected_oom:
            report_oom("parser_oom_cleanup", "started")
        docker("rm", "--force", identifier)
        if expected_oom:
            report_oom("parser_oom_cleanup", "complete")


def report_stage(stage: str) -> None:
    """Emit only fixed source-owned phases; reporting cannot mask test failures."""
    if stage not in {"build", "parser", "oom", "complete"}:
        return
    output = os.environ.get("GITHUB_OUTPUT")
    if os.environ.get("EM_PARSER_STAGE_REPORT") != "true" or not output:
        return
    try:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write("parser_stage=" + stage + "\n")
    except OSError:
        pass


def execute(root: Path) -> None:
    stage = "build"
    try:
        docker(
            "build",
            "--file",
            str(root / "scripts/isolation/Dockerfile.parser"),
            "--tag",
            IMAGE,
            str(root),
            timeout=600,
        )
        stage = "parser"
        run(["python", "/app/parser_acceptance.py"])
        # The same network-none memory limit remains an actual mandatory test.
        stage = "oom"
        evidence = run(
            ["python", "-c", "chunks=[]\nwhile True: chunks.append(bytearray(8 * 1024 * 1024))"],
            expected_oom=True,
        )
        print(json.dumps({"diagnostic": "parser-memory-limit", **evidence}))
        stage = "complete"
    finally:
        report_stage(stage)


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Reviewed disposable CI environment required")
    execute(Path(__file__).resolve().parents[2])


if __name__ == "__main__":
    main()
