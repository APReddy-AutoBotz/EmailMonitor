"""One exact initial-event private diagnostic; never a general acquisition route.

Only fixed aggregate counters leave the guest. Output follows both independent
cleanup checks; no source bytes, identity, private path or exception is logged.
This admits one initial-event attempt, not a persistent global replay guarantee.
"""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args
from uuid import uuid4

from run_private_sample_once import CORPUS_PATH, DIGEST, REVISION, SIZE
from run_private_sample_once import acquire as acquire
from run_private_sample_once import read_event as read_event
from run_private_sample_once import remove_private as remove_private

if TYPE_CHECKING:
    from emailmonitor.parsing.affiliation_diagnostic import AffiliationDiagnostic
    from emailmonitor.parsing.private_affiliation_diagnostic import (
        PrivateAffiliationDiagnosticManifest,
    )

ROOT = Path(__file__).resolve().parents[2]
REPO = "APReddy-AutoBotz/EmailMonitor"
HEAD_REF = "feat/elsevier-one-sample-affiliation-diagnostic"
BASE_REF = "feat/synthetic-affiliation-diagnostic"
BASE_SHA = "93f72166ea246b47f585bf278d681bff8dc2fe79"
PR_NUMBER = 44
REVIEW = "em015-elsevier-ccby3-affiliation-diagnostic-20261020"
MAX_OUTPUT = 4096
Reason = Literal[
    "runner_refused",
    "preparation_refused",
    "acquisition_refused",
    "diagnostic_refused",
    "cleanup_refused",
]
Cleanup = Literal["verified", "not_started", "refused"]


class Refused(Exception):
    """A closed internal refusal; never serialize exception details."""


def require_context(environ: Mapping[str, str], event: Mapping[str, Any]) -> str:
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/pull/44/merge",
        "GITHUB_HEAD_REF": HEAD_REF,
        "GITHUB_BASE_REF": BASE_REF,
    }
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
    if (
        any(environ.get(key) != value for key, value in expected.items())
        or any(
            value
            for key, value in environ.items()
            if key.upper() in forbidden or key.upper().endswith("_PROXY")
        )
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
    ):
        raise Refused()
    repository = event.get("repository")
    pr = event.get("pull_request")
    if (
        event.get("action") != "opened"
        or type(event.get("number")) is not int
        or event["number"] != PR_NUMBER
        or not isinstance(repository, dict)
        or repository.get("full_name") != REPO
        or not isinstance(pr, dict)
        or type(pr.get("number")) is not int
        or pr["number"] != PR_NUMBER
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
        or re.fullmatch(r"[a-f0-9]{40}", sha) is None
    ):
        raise Refused()
    return sha


def fixed_manifest() -> PrivateAffiliationDiagnosticManifest:
    from emailmonitor.parsing.private_affiliation_diagnostic import (
        PURPOSE,
        REPOSITORY,
        PrivateAffiliationDiagnosticManifest,
    )
    from emailmonitor.sources.sciencedirect import ArticleIdentifier

    return PrivateAffiliationDiagnosticManifest(
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


def diagnostic_values(result: AffiliationDiagnostic) -> dict[str, Any]:
    from emailmonitor.parsing.affiliation_diagnostic import (
        AffiliationDiagnostic,
        decode_output,
        encode_output,
    )

    if type(result) is not AffiliationDiagnostic or set(result.__dict__) != set(
        AffiliationDiagnostic.model_fields
    ):
        raise Refused()
    # Revalidate even a constructed or mutated model. Canonical PR43 decoding
    # enforces exact fields, fixed profile and twelve strict bounded integers.
    validated = AffiliationDiagnostic.model_validate(result.model_dump(warnings="error"))
    return decode_output(encode_output(validated)).model_dump(warnings="error")


def evaluate(path: Path, manifest: PrivateAffiliationDiagnosticManifest) -> dict[str, Any]:
    from emailmonitor.parsing.private_affiliation_diagnostic import (
        PURPOSE,
        AffiliationDiagnosticRightsDecision,
        PrivateAffiliationDiagnosticResult,
        evaluate_private_affiliation_diagnostic,
    )
    from emailmonitor.parsing.private_affiliation_diagnostic import Refusal as PrivateRefusal

    result = evaluate_private_affiliation_diagnostic(
        path,
        manifest,
        AffiliationDiagnosticRightsDecision(manifest.digest(), PURPOSE, "cleared", REVIEW),
    )
    if (
        type(result) is not PrivateAffiliationDiagnosticResult
        or set(result.__dict__) != {"status", "reasons", "diagnostic"}
        or type(result.status) is not str
        or type(result.reasons) is not tuple
    ):
        raise Refused()
    if result.status == "refused":
        if (
            result.diagnostic is not None
            or len(result.reasons) != 1
            or type(result.reasons[0]) is not str
            or result.reasons[0] not in get_args(PrivateRefusal)
        ):
            raise Refused()
        raise Refused()
    if result.status != "diagnosed" or result.reasons or result.diagnostic is None:
        raise Refused()
    return diagnostic_values(result.diagnostic)


def refusal(reason: Reason, cleanup: Cleanup) -> dict[str, Any]:
    return {"status": "refused", "reasons": [reason], "diagnostic": None, "cleanup_status": cleanup}


def validate_counters(value: object) -> None:
    from emailmonitor.parsing.affiliation_diagnostic import AffiliationDiagnostic

    if type(value) is not dict or set(value) != set(AffiliationDiagnostic.model_fields):
        raise Refused()
    diagnostic_values(AffiliationDiagnostic.model_validate(value))


def encode_result(result: object) -> bytes:
    """Final closed public schema, independently checked after all cleanup."""
    if type(result) is not dict or set(result) != {
        "status",
        "reasons",
        "diagnostic",
        "cleanup_status",
    }:
        raise Refused()
    if (
        type(result["status"]) is not str
        or type(result["cleanup_status"]) is not str
        or result["cleanup_status"] not in get_args(Cleanup)
        or type(result["reasons"]) is not list
    ):
        raise Refused()
    if result["status"] == "diagnosed":
        if result["cleanup_status"] != "verified" or result["reasons"]:
            raise Refused()
        validate_counters(result["diagnostic"])
    elif result["status"] == "refused":
        reasons = result["reasons"]
        if (
            result["diagnostic"] is not None
            or len(reasons) != 1
            or type(reasons[0]) is not str
            or reasons[0] not in get_args(Reason)
            or (result["cleanup_status"] == "refused") != (reasons == ["cleanup_refused"])
            or (result["cleanup_status"] == "not_started" and reasons != ["runner_refused"])
        ):
            raise Refused()
    else:
        raise Refused()
    output = (
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        + b"\n"
    )
    if len(output) > MAX_OUTPUT:
        raise Refused()
    return output


def interrupted(signum: int, frame: object) -> None:
    raise Refused()


def cleanup_owned(
    integration: Any, owned: Any, alias: Any, temporary: tempfile.TemporaryDirectory[str] | None
) -> bool:
    """Shield ordinary termination while independently bounding both cleanups."""
    previous = None
    mask: set[int | signal.Signals] | None = None
    restored = True
    try:
        # Defer ordinary signals through setup, both checks and transitions.
        # SIGALRM remains available to enforce each separate cleanup budget.
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        previous = signal.getsignal(signal.SIGALRM)
    except BaseException:
        restored = False

    def bounded(action: Callable[[], bool], seconds: int) -> bool:
        verified = False
        try:
            # A single ordinary interruption while arming a phase cannot skip
            # the next independent phase. No resource operation is retried here.
            for attempt in range(2):
                try:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, integration.cleanup_deadline)
                    signal.alarm(seconds)
                    break
                except Refused:
                    if attempt:
                        raise
            verified = action() is True
        except BaseException:
            pass
        finally:
            try:
                signal.alarm(0)
            except BaseException:
                verified = False
        return verified

    private_removed = False
    cleaned = False
    try:
        private_removed = bounded(lambda: remove_private(temporary), 30)
    finally:
        try:
            cleaned = bounded(lambda: integration.reconcile(owned, alias), 180)
        finally:
            try:
                if previous is not None:
                    signal.signal(signal.SIGALRM, previous)
            except BaseException:
                restored = False
            if mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, mask)
                except BaseException:
                    # Pending ordinary termination is delivered only after both
                    # checks. It cannot leak an exception or undo reconciliation.
                    restored = False
    return private_removed and cleaned and restored


def execute(environ: Mapping[str, str], event: Mapping[str, Any]) -> dict[str, Any]:
    try:
        sha = require_context(environ, event)
        import run_xml_integration as integration

        runtime = integration.load_runtime()
        if runtime.command(["git", "rev-parse", "HEAD"], timeout=10).decode("ascii").strip() != sha:
            raise Refused()
        from emailmonitor.parsing import affiliation_diagnostic_channel as channel

        owned = runtime.OwnedXmlBuilds(uuid4().hex)
    except BaseException:
        return refusal("runner_refused", "not_started")
    original_verify = channel.verify_profile
    alias = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    stage: Reason = "preparation_refused"
    counters: dict[str, Any] | None = None
    succeeded = False
    try:
        image_id, _ = integration.prepare_image(runtime, owned)
        alias = integration.OwnedAlias(owned, image_id, runtime.command)
        alias.install()
        alias.verify()

        def verify_private(metadata: Mapping[str, object]) -> None:
            # Preserve the exact original diagnostic-profile check and original
            # metadata; ownership is an additional check, never a rewrite.
            original_verify(metadata)
            config = metadata.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
            if (
                metadata.get("Image") != image_id
                or not isinstance(labels, dict)
                or labels.get(runtime.LABEL) != owned.owner
            ):
                raise Refused()

        channel.verify_profile = verify_private
        temporary = tempfile.TemporaryDirectory(prefix="em-private-affiliation-once-", dir="/tmp")
        with temporary as directory:
            private = Path(directory)
            if (
                private.resolve().is_relative_to(ROOT.resolve())
                or stat.S_IMODE(private.stat().st_mode) != 0o700
            ):
                raise Refused()
            path = private / "sample.norm-xml"
            stage = "acquisition_refused"
            signal.alarm(40)  # Bounds DNS/header stalls as well as fixed GET reads.
            body = acquire()
            signal.alarm(120)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                os.fchmod(target.fileno(), 0o600)
                if target.write(body) != len(body):
                    raise Refused()
            del body
            stage = "diagnostic_refused"
            manifest = fixed_manifest()
            alias.verify()
            counters = evaluate(path, manifest)
            # Revalidate even the composer return before retaining public fields.
            validate_counters(counters)
            alias.verify()
        succeeded = True
    except BaseException:
        counters = None
    finally:
        try:
            cleaned = cleanup_owned(integration, owned, alias, temporary)
        finally:
            channel.verify_profile = original_verify
    if not cleaned:
        return refusal("cleanup_refused", "refused")
    if not succeeded:
        return refusal(stage, "verified")
    return {
        "status": "diagnosed",
        "reasons": [],
        "diagnostic": counters,
        "cleanup_status": "verified",
    }


def main() -> None:
    result = refusal("runner_refused", "not_started")
    previous: dict[int, Any] = {}
    try:
        if len(sys.argv) != 1:
            raise Refused()
        event = read_event(os.environ["GITHUB_EVENT_PATH"])
        require_context(os.environ, event)
        os.chdir(ROOT)
        for kind in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            previous[kind] = signal.signal(kind, interrupted)
        signal.alarm(600)
        # An unexpected escape after resources may exist must never claim that
        # cleanup was not started or verified.
        result = refusal("cleanup_refused", "refused")
        result = execute(dict(os.environ), event)
    except BaseException:
        pass
    finally:
        signal.alarm(0)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    # All refusal entry paths remain usable with stdlib alone.
    try:
        output = encode_result(result)
    except BaseException:
        result = refusal("cleanup_refused", "refused")
        output = encode_result(result)
    sys.stdout.write(output.decode("ascii"))
    sys.stdout.flush()
    if result["status"] == "refused":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
