"""Authored pinned-parser lifecycle tests; no Docker daemon or subprocess runs."""

import copy
import json
from typing import Any

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import XmlObservation, parse_article
from emailmonitor.extraction.xml_service import fixture_bytes
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing import xml_channel as legacy
from emailmonitor.parsing.xml_channel import fixture_expectation
from emailmonitor.parsing.xml_protocol import encode_input
from emailmonitor.runtime import pinned_xml as channel

IMAGE_ID = "sha256:" + "a" * 64
CONTAINER_ID = "b" * 64
OWNER = "c" * 32
NAME = "emailmonitor-service-xml-" + OWNER
LABEL = "io.emailmonitor.controlled-parser-owner"
SETTINGS = Settings(environment="test", fixture_mode=True)


def metadata() -> dict[str, Any]:
    return {
        "Id": CONTAINER_ID,
        "Name": "/" + NAME,
        "Image": IMAGE_ID,
        "Mounts": [],
        "HostConfig": {
            "NetworkMode": "none",
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "ReadonlyRootfs": True,
            "Memory": 134217728,
            "MemorySwap": 134217728,
            "PidsLimit": 32,
            "NanoCpus": 500000000,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
            "Ulimits": [
                {"Name": "nofile", "Hard": 64, "Soft": 64},
                {"Name": "core", "Hard": 0, "Soft": 0},
            ],
        },
        "Config": {
            "User": "65532:65532",
            "Cmd": list(legacy.COMMAND),
            "Env": ["PATH=/usr/local/bin:/usr/bin", "EM_ISOLATION_DIAGNOSTIC=synthetic-test-only"],
            "Labels": {LABEL: OWNER},
        },
        "State": {"Running": False, "ExitCode": 0, "OOMKilled": False},
    }


class DockerDouble:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.initial = metadata()
        self.final = metadata()
        self.cleanup = metadata()
        self.image: object = [{"Id": IMAGE_ID}]
        self.calls: list[tuple[str, ...]] = []
        self.starts: list[list[str]] = []
        self.create_reply = (CONTAINER_ID + "\n").encode()
        self.create_error: BaseException | None = None
        self.exchange_error: BaseException | None = None
        self.cleanup_error = False
        self.remove_error = False
        self.remaining = b""
        self.inspections = 0
        self.data = fixture_bytes()
        self.expected = fixture_expectation()
        self.observation = parse_article(self.data, self.expected.requested_identifier)
        self.output = (
            json.dumps(
                {
                    "profile": "network-none-parser-v1",
                    "observation": self.observation.model_dump(mode="json"),
                }
            ).encode()
            + b"\n"
        )
        monkeypatch.setattr("secrets.token_hex", lambda size: OWNER)
        monkeypatch.setattr(channel, "_docker", self.docker)
        monkeypatch.setattr(channel, "exchange", self.exchange)

    def docker(self, *args: str, timeout: float = 15) -> bytes:
        assert 0 < timeout <= 15
        self.calls.append(args)
        if args == ("image", "inspect", IMAGE_ID):
            return json.dumps(self.image).encode()
        if args[0] == "create":
            if self.create_error:
                raise self.create_error
            return self.create_reply
        if args == ("inspect", CONTAINER_ID):
            self.inspections += 1
            return json.dumps([self.initial if self.inspections == 1 else self.final]).encode()
        if args == ("inspect", NAME):
            if self.cleanup_error:
                raise IsolationUnavailable("inspect_failed")
            return json.dumps([self.cleanup]).encode()
        if args == ("rm", "--force", CONTAINER_ID):
            if self.remove_error:
                raise IsolationUnavailable("remove_failed")
            return b""
        if args == ("ps", "--all", "--quiet", "--no-trunc", "--filter", "id=" + CONTAINER_ID):
            return self.remaining
        raise AssertionError(f"Unexpected Docker command: {args}")

    def exchange(self, command: list[str], data: bytes, timeout: float = 30) -> bytes:
        self.starts.append(command)
        assert data == encode_input(self.data, self.expected)
        assert 0 < timeout <= 30
        if self.exchange_error:
            raise self.exchange_error
        return self.output

    def parse(self) -> XmlObservation:
        return channel.parse_pinned(SETTINGS, self.data, expected=self.expected, image_id=IMAGE_ID)

    def assert_removed(self) -> None:
        assert ("rm", "--force", CONTAINER_ID) in self.calls
        assert self.calls[-1] == (
            "ps",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "id=" + CONTAINER_ID,
        )


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> DockerDouble:
    return DockerDouble(monkeypatch)


def test_pinned_success_uses_exact_immutable_artifact(docker: DockerDouble) -> None:
    original = (legacy.PROFILE, legacy.COMMAND, legacy.IMAGE, legacy.PRIVATE_PROFILE)
    assert docker.parse() == docker.observation
    assert docker.calls[0] == ("image", "inspect", IMAGE_ID)
    assert docker.calls[1] == (
        "create",
        "--pull=never",
        "--interactive",
        "--name=" + NAME,
        "--label=" + LABEL + "=" + OWNER,
        *legacy.PROFILE,
        IMAGE_ID,
        *legacy.COMMAND,
    )
    assert docker.starts == [["docker", "start", "--attach", "--interactive", CONTAINER_ID]]
    docker.assert_removed()
    assert original == (legacy.PROFILE, legacy.COMMAND, legacy.IMAGE, legacy.PRIVATE_PROFILE)


@pytest.mark.parametrize("image_id", ["latest", "sha256:" + "A" * 64, "a" * 64, "", "sha256:abc"])
def test_invalid_image_refused_before_docker(docker: DockerDouble, image_id: str) -> None:
    with pytest.raises(IsolationUnavailable, match="image_identity_invalid"):
        channel.parse_pinned(SETTINGS, docker.data, expected=docker.expected, image_id=image_id)
    assert not docker.calls


def test_nonfixture_and_bad_bytes_refused_before_docker(docker: DockerDouble) -> None:
    with pytest.raises(IsolationUnavailable, match="explicit_test_mode"):
        channel.parse_pinned(
            Settings(environment="test", fixture_mode=False),
            docker.data,
            expected=docker.expected,
            image_id=IMAGE_ID,
        )
    with pytest.raises(ValueError, match="provenance"):
        channel.parse_pinned(SETTINGS, b"wrong", expected=docker.expected, image_id=IMAGE_ID)
    assert not docker.calls


@pytest.mark.parametrize("image", [[], [{"Id": "sha256:" + "d" * 64}], [{"Id": IMAGE_ID}] * 2])
def test_image_inspection_mismatch_never_creates(docker: DockerDouble, image: object) -> None:
    docker.image = image
    with pytest.raises(IsolationUnavailable, match="image_identity_mismatch"):
        docker.parse()
    assert len(docker.calls) == 1


@pytest.mark.parametrize(
    "field,value", [("Id", "d" * 64), ("Name", "/other"), ("Image", "sha256:" + "d" * 64)]
)
def test_child_identity_mismatch_before_start(docker: DockerDouble, field: str, value: str) -> None:
    docker.initial[field] = value
    with pytest.raises(IsolationUnavailable, match="container_identity_mismatch"):
        docker.parse()
    assert not docker.starts
    docker.assert_removed()


@pytest.mark.parametrize(
    "env",
    [
        [],
        ["EM_ISOLATION_DIAGNOSTIC=wrong"],
        ["EM_ISOLATION_DIAGNOSTIC=synthetic-test-only"] * 2,
        ["EM_ISOLATION_DIAGNOSTIC=synthetic-test-only", "SECRET=forbidden"],
        ["EM_ISOLATION_DIAGNOSTIC=synthetic-test-only", "PATH"],
        ["EM_ISOLATION_DIAGNOSTIC=synthetic-test-only", 12],
    ],
)
def test_environment_refused_before_start(docker: DockerDouble, env: object) -> None:
    docker.initial["Config"]["Env"] = env
    with pytest.raises(IsolationUnavailable, match="environment_invalid"):
        docker.parse()
    assert not docker.starts
    docker.assert_removed()


@pytest.mark.parametrize(
    "field,value",
    [("NetworkMode", "host"), ("Privileged", True), ("Memory", 0), ("Binds", ["/tmp:/host"])],
)
def test_isolation_profile_refused_before_start(
    docker: DockerDouble, field: str, value: object
) -> None:
    docker.initial["HostConfig"][field] = value
    with pytest.raises(ValueError, match="configuration mismatch"):
        docker.parse()
    assert not docker.starts
    docker.assert_removed()


@pytest.mark.parametrize("field,value", [("Running", True), ("ExitCode", 1), ("OOMKilled", True)])
def test_failed_parser_state_cleans_up(docker: DockerDouble, field: str, value: object) -> None:
    docker.final["State"][field] = value
    with pytest.raises(IsolationUnavailable, match="exit_invalid"):
        docker.parse()
    docker.assert_removed()


@pytest.mark.parametrize("output", [b"", b"{}\n", b"{}\ntrailing", b"x" * 131073])
def test_untrusted_output_refused_and_cleaned(docker: DockerDouble, output: bytes) -> None:
    docker.output = output
    with pytest.raises(ValueError):
        docker.parse()
    docker.assert_removed()


def test_output_identity_mismatch_is_refused(docker: DockerDouble) -> None:
    observed = docker.observation.model_dump(mode="json")
    observed["content_digest"] = "d" * 64
    docker.output = (
        json.dumps({"profile": "network-none-parser-v1", "observation": observed}).encode() + b"\n"
    )
    with pytest.raises(ValueError):
        docker.parse()
    docker.assert_removed()


@pytest.mark.parametrize("create_failed", [False, True])
def test_uncertain_create_recovers_by_owned_name(docker: DockerDouble, create_failed: bool) -> None:
    if create_failed:
        docker.create_error = IsolationUnavailable("create_failed")
    else:
        docker.create_reply = b"malformed\n"
    with pytest.raises(IsolationUnavailable):
        docker.parse()
    assert not docker.starts
    docker.assert_removed()


@pytest.mark.parametrize("mutation", ["owner", "name", "image", "id"])
def test_cleanup_never_removes_foreign_identity(docker: DockerDouble, mutation: str) -> None:
    if mutation == "owner":
        docker.cleanup["Config"]["Labels"][LABEL] = "other"
    else:
        docker.cleanup[{"name": "Name", "image": "Image", "id": "Id"}[mutation]] = "other"
    with pytest.raises(IsolationUnavailable, match="cleanup_failed"):
        docker.parse()
    assert not any(call[0] == "rm" for call in docker.calls)


@pytest.mark.parametrize("failure", ["inspect", "remove", "remaining"])
def test_uncertain_cleanup_cannot_return_success(docker: DockerDouble, failure: str) -> None:
    docker.cleanup_error = failure == "inspect"
    docker.remove_error = failure == "remove"
    docker.remaining = CONTAINER_ID.encode() if failure == "remaining" else b""
    with pytest.raises(IsolationUnavailable, match="cleanup_failed"):
        docker.parse()


def test_primary_failure_preserved_when_cleanup_fails(docker: DockerDouble) -> None:
    primary = IsolationUnavailable("original_parser_timeout")
    docker.exchange_error = primary
    docker.cleanup_error = True
    with pytest.raises(IsolationUnavailable, match="original_parser_timeout") as caught:
        docker.parse()
    assert caught.value is primary
    assert caught.value.__notes__ == ["Owned XML parser cleanup failed"]


def test_create_failure_without_inspectable_child_reports_uncertainty(docker: DockerDouble) -> None:
    primary = IsolationUnavailable("create_failed")
    docker.create_error = primary
    docker.cleanup_error = True
    with pytest.raises(IsolationUnavailable) as caught:
        docker.parse()
    assert caught.value is primary
    assert caught.value.__notes__ == ["Owned XML parser cleanup failed"]
    assert not any(call[0] == "rm" for call in docker.calls)


def test_final_identity_change_is_refused(docker: DockerDouble) -> None:
    docker.final = copy.deepcopy(docker.final)
    docker.final["Image"] = "sha256:" + "d" * 64
    with pytest.raises(IsolationUnavailable, match="identity_mismatch"):
        docker.parse()
    docker.assert_removed()
