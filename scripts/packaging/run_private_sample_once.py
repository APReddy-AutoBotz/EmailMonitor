"""One initial PR-event attempt at one approved immutable sample; no live adapter.

No event replay ledger is claimed. Abrupt runner loss relies on hosted VM disposal.
No body, observation, traceback, private path or arbitrary subprocess output is logged.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import re
import signal
import socket
import ssl
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
REPO = "APReddy-AutoBotz/EmailMonitor"
HEAD_REF = "feat/elsevier-one-sample-validation"
BASE_REF = "feat/private-offline-sample-admission"
BASE_SHA = "158c7db1005a3398604aeca4cd60fdaca176ce9b"
REVISION = "0ed398ec9288fd8936a24f9486647ecfcbf2d972"
CORPUS_PATH = "SourceXML/S0960148113005727.norm-xml"
HOST = "raw.githubusercontent.com"
SOURCE_PATH = f"/elsevierlabs/OA-STM-Corpus/{REVISION}/{CORPUS_PATH}"
SIZE = 143976
DIGEST = "7c0add248911ef4a442b5a0b9569c605bf47aee2ccfc1315bfba7bf25d1e2c25"
REVIEW = "em015-elsevier-ccby3-single-sample-20261020"


class Refused(Exception):
    """Internal fixed refusal, never an external error/body."""


def require_context(environ: Mapping[str, str], event: Mapping[str, Any]) -> str:
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/pull/42/merge",
        "GITHUB_HEAD_REF": HEAD_REF,
        "GITHUB_BASE_REF": BASE_REF,
    }
    if any(environ.get(key) != value for key, value in expected.items()):
        raise Refused()
    forbidden = {
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "SSLKEYLOGFILE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "PYTHONHTTPSVERIFY",
        "ELSEVIER_API_KEY",
        "ELS_API_KEY",
        "ELSEVIER_INSTTOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    }
    if any(
        value
        for key, value in environ.items()
        if key in forbidden or key.upper().endswith("_PROXY")
    ):
        raise Refused()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise Refused()
    pr = event.get("pull_request")
    if (
        event.get("action") != "opened"
        or type(event.get("number")) is not int
        or event["number"] != 42
        or not isinstance(pr, dict)
    ):
        raise Refused()
    head, base = pr.get("head"), pr.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise Refused()
    for item, ref in ((head, HEAD_REF), (base, BASE_REF)):
        repository = item.get("repo")
        if (
            item.get("ref") != ref
            or not isinstance(repository, dict)
            or repository.get("full_name") != REPO
        ):
            raise Refused()
    sha = head.get("sha")
    if (
        base.get("sha") != BASE_SHA
        or not isinstance(sha, str)
        or not re.fullmatch(r"[a-f0-9]{40}", sha)
    ):
        raise Refused()
    return sha


def read_event(path: str) -> dict[str, Any]:
    with open(path, "rb") as source:
        data = source.read(1048577)
    if len(data) > 1048576:
        raise Refused()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise Refused()
            result[key] = value
        return result

    value = json.loads(data, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise Refused()
    return value


def acquire() -> bytes:
    """One fixed anonymous GET, one selected public IP, no redirect or retry."""
    from emailmonitor.fetching.safety import ConnectionPlan, classify_url

    url = classify_url("https://" + HOST + SOURCE_PATH, frozenset({HOST}))
    deadline = time.monotonic() + 30
    records = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    plan = ConnectionPlan.from_records(url, tuple(str(record[4][0]) for record in records))
    address = sorted(plan.addresses)[0]
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise Refused()

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise Refused()
        return min(10, value)

    # Literal-IP connect prevents a second DNS lookup; all returned DNS addresses
    # are checked before selection. TLS verifies the original hostname and SNI.
    with socket.socket(family, socket.SOCK_STREAM) as raw:
        raw.settimeout(remaining())
        raw.connect((address, 443))
        if str(raw.getpeername()[0]) != address:
            raise Refused()
        with context.wrap_socket(raw, server_hostname=HOST) as secured:
            if str(secured.getpeername()[0]) != address:
                raise Refused()
            plan.validate_peer(str(secured.getpeername()[0]), True)
            secured.settimeout(remaining())
            secured.sendall(
                (
                    f"GET {SOURCE_PATH} HTTP/1.1\r\nHost: {HOST}\r\n"
                    "Accept: text/plain\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
            )
            with http.client.HTTPResponse(secured) as response:
                response.begin()
                headers = response.getheaders()
                lengths = [value for name, value in headers if name.lower() == "content-length"]
                if (
                    response.status != 200
                    or lengths != [str(SIZE)]
                    or response.getheader("Transfer-Encoding") is not None
                    or response.getheader("Content-Encoding") not in (None, "identity")
                    or response.getheader("Location") is not None
                ):
                    raise Refused()
                data = bytearray()
                while True:
                    secured.settimeout(remaining())
                    chunk = response.read1(min(8192, SIZE + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > SIZE:
                        raise Refused()
                remaining()
    body = bytes(data)
    if len(body) != SIZE or hashlib.sha256(body).hexdigest() != DIGEST:
        raise Refused()
    return body


def fixed_manifest() -> Any:
    from emailmonitor.parsing.private_sample import PURPOSE, REPOSITORY, PrivateSampleManifest
    from emailmonitor.sources.sciencedirect import ArticleIdentifier

    return PrivateSampleManifest(
        repository=REPOSITORY,
        revision=REVISION,
        corpus_path=CORPUS_PATH,
        evidence_url=f"{REPOSITORY}/blob/{REVISION}/{CORPUS_PATH}",
        acquired_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        byte_size=SIZE,
        sha256=DIGEST,
        requested_identifier=ArticleIdentifier(kind="doi", value="10.1016/j.renene.2013.10.041"),
        source_profile="xocs_document",
        purpose=PURPOSE,
    )


def evaluate(path: Path, manifest: Any) -> dict[str, Any]:

    from emailmonitor.extraction.sciencedirect import Reason
    from emailmonitor.parsing.private_sample import (
        PURPOSE,
        PrivateSampleResult,
        RightsDecision,
        evaluate_private_sample,
    )
    from emailmonitor.parsing.private_sample import Refusal as SampleRefusal

    result = evaluate_private_sample(
        path, manifest, RightsDecision(manifest.digest(), PURPOSE, "cleared", REVIEW)
    )
    if (
        type(result) is not PrivateSampleResult
        or result.status not in {"observed", "no_contact", "partial", "unsupported", "refused"}
        or any(
            reason not in (*get_args(Reason), *get_args(SampleRefusal)) for reason in result.reasons
        )
        or any(
            type(count) is not int or not 0 <= count <= 100
            for count in (result.author_count, result.candidate_count)
        )
    ):
        raise Refused()
    return asdict(result)


def interrupted(signum: int, frame: object) -> None:
    raise Refused()


def remove_private(temporary: tempfile.TemporaryDirectory[str] | None) -> bool:
    """Retry only this invocation's owned directory; absence is required."""
    if temporary is None:
        return True
    for _ in range(2):
        try:
            temporary.cleanup()
            if not os.path.lexists(temporary.name):
                return True
        except Exception:
            # Includes ordinary termination during the first deletion attempt.
            # The outer alarm bounds both retries even when deletion stalls.
            pass
    return False


def execute(environ: Mapping[str, str], event: Mapping[str, Any]) -> dict[str, Any]:
    sha = require_context(environ, event)
    import run_xml_integration as integration

    runtime = integration.load_runtime()
    if runtime.command(["git", "rev-parse", "HEAD"], timeout=10).decode("ascii").strip() != sha:
        raise Refused()
    owned = runtime.OwnedXmlBuilds(uuid4().hex)
    from emailmonitor.parsing import xml_channel

    original_verify = xml_channel.verify_profile
    alias = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    result: dict[str, Any] = {
        "status": "refused",
        "reasons": ["preparation_refused"],
        "author_count": 0,
        "candidate_count": 0,
    }
    try:
        image_id, _ = integration.prepare_image(runtime, owned)
        alias = integration.OwnedAlias(owned, image_id, runtime.command)
        alias.install()
        alias.verify()

        def verify_private(
            metadata: Mapping[str, object], *, private_offline: bool = False
        ) -> None:
            if private_offline is not True:
                raise Refused()
            original_verify(metadata, private_offline=True)
            config = metadata.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
            if (
                metadata.get("Image") != image_id
                or not isinstance(labels, dict)
                or labels.get(runtime.LABEL) != owned.owner
            ):
                raise Refused()

        xml_channel.verify_profile = verify_private
        # The private file is created only after the complete build/probe, under
        # a new mode-0700 directory outside the checkout/build/archive context.
        temporary = tempfile.TemporaryDirectory(prefix="em-private-once-", dir="/tmp")
        with temporary as directory:
            path = Path(directory) / "sample.norm-xml"
            result["reasons"] = ["acquisition_refused"]
            signal.alarm(40)  # Also bounds DNS/header stalls before socket reads.
            body = acquire()
            signal.alarm(120)
            with path.open("xb") as target:
                os.chmod(path, 0o600)
                target.write(body)
            del body
            manifest = fixed_manifest()
            alias.verify()
            result["reasons"] = ["evaluation_refused"]
            result = evaluate(path, manifest)
            alias.verify()
    except Exception:
        # No traceback or error text, including nested parser/control failures.
        result = {
            "status": "refused",
            "reasons": result["reasons"]
            if result["status"] == "refused"
            else ["evaluation_refused"],
            "author_count": 0,
            "candidate_count": 0,
        }
    finally:
        xml_channel.verify_profile = original_verify
        signal.alarm(0)
        previous = signal.signal(signal.SIGALRM, integration.cleanup_deadline)
        signal.alarm(30)
        private_removed = False
        try:
            private_removed = remove_private(temporary)
        except BaseException:
            pass
        finally:
            signal.alarm(0)
        # Reconcile Docker even if private removal failed, but never call the
        # overall cleanup verified unless both independent checks succeeded.
        signal.alarm(180)
        cleaned = False
        try:
            cleaned = integration.reconcile(owned, alias)
        except BaseException:
            pass
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        if not cleaned or not private_removed:
            result = {
                "status": "refused",
                "reasons": ["cleanup_refused"],
                "author_count": 0,
                "candidate_count": 0,
            }
    return result


def main() -> None:
    if len(sys.argv) != 1:
        raise Refused()
    event = read_event(os.environ["GITHUB_EVENT_PATH"])
    require_context(os.environ, event)
    os.chdir(ROOT)
    previous = {
        kind: signal.signal(kind, interrupted)
        for kind in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM)
    }
    signal.alarm(600)
    try:
        result = execute(dict(os.environ), event)
    finally:
        signal.alarm(0)
        for kind, handler in previous.items():
            signal.signal(kind, handler)
    print(json.dumps(result, sort_keys=True), flush=True)
    if result["status"] == "refused":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            '{"status":"refused","reasons":["runner_refused"],"author_count":0,"candidate_count":0}'
        )
        raise SystemExit(1) from None
