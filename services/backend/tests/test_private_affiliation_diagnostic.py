"""Only authored synthetic bytes and mock transport, never actual rights clearance."""

import hashlib
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from emailmonitor.extraction.sciencedirect import MAX_BYTES
from emailmonitor.parsing import private_affiliation_diagnostic as admission
from emailmonitor.parsing.affiliation_diagnostic import diagnose, encode_output
from emailmonitor.parsing.private_affiliation_diagnostic import (
    PURPOSE,
    REPOSITORY,
    AffiliationDiagnosticRightsDecision,
    PrivateAffiliationDiagnosticManifest,
    PrivateAffiliationDiagnosticResult,
    evaluate_private_affiliation_diagnostic,
)
from emailmonitor.parsing.private_sample import PURPOSE as OLD_PURPOSE
from emailmonitor.parsing.private_sample import PrivateSampleManifest, RightsDecision
from test_affiliation_diagnostic_channel import docker_double
from test_affiliation_diagnostic_reproduction import IDENTIFIER, synthetic


def prepare(
    tmp_path: Path,
) -> tuple[Path, bytes, PrivateAffiliationDiagnosticManifest, AffiliationDiagnosticRightsDecision]:
    data = synthetic(reference="cor")
    path = tmp_path / "synthetic.norm-xml"
    path.write_bytes(data)
    corpus_path = "SourceXML/S0000000000000001.norm-xml"
    manifest = PrivateAffiliationDiagnosticManifest(
        repository=REPOSITORY,
        revision="a" * 40,
        corpus_path=corpus_path,
        evidence_url=f"{REPOSITORY}/blob/{'a' * 40}/{corpus_path}",
        acquired_at="2026-10-01T00:00:00Z",
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        requested_identifier=IDENTIFIER,
        source_profile="xocs_document",
        purpose=PURPOSE,
    )
    rights = AffiliationDiagnosticRightsDecision(
        manifest.digest(), PURPOSE, "cleared", "synthetic-diagnostic-review-only"
    )
    return path, data, manifest, rights


def never(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Unadmitted bytes reached a later boundary")


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "https://github.com/other/OA-STM-Corpus"),
        ("revision", "main"),
        ("revision", "A" * 40),
        ("corpus_path", "SourceXML/../secret.norm-xml"),
        ("corpus_path", "SourceXML/synthetic.xml"),
        ("evidence_url", "https://example.org/synthetic"),
        ("acquired_at", "2099-01-01T00:00:00Z"),
        ("acquired_at", "2026-02-30T00:00:00Z"),
        ("byte_size", 0),
        ("byte_size", MAX_BYTES + 1),
        ("byte_size", True),
        ("sha256", "z" * 64),
        ("source_profile", "article_retrieval_response"),
        ("purpose", OLD_PURPOSE),
        ("requested_identifier", {"kind": "doi", "value": "invalid"}),
        ("approved", True),
    ],
)
def test_manifest_refusal_precedes_file_and_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    path, _, manifest, rights = prepare(tmp_path)
    monkeypatch.setattr(admission, "_read_regular", never)
    monkeypatch.setattr(admission, "diagnose_in_container", never)
    changed = manifest.model_copy(update={field: value})
    assert evaluate_private_affiliation_diagnostic(path, changed, rights) == (
        PrivateAffiliationDiagnosticResult("refused", ("manifest_refused",))
    )


@pytest.mark.parametrize(
    "change",
    [
        {"disposition": "unresolved"},
        {"disposition": "denied"},
        {"disposition": True},
        {"scope": OLD_PURPOSE},
        {"scope": "retention-export"},
        {"manifest_digest": "0" * 64},
        {"review_reference": ""},
        {"review_reference": "arbitrary\ncontent"},
        {"review_reference": "x" * 201},
    ],
)
def test_diagnostic_rights_must_be_independently_scoped_and_manifest_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    path, _, manifest, rights = prepare(tmp_path)
    monkeypatch.setattr(admission, "_read_regular", never)
    monkeypatch.setattr(admission, "diagnose_in_container", never)
    assert evaluate_private_affiliation_diagnostic(
        path, manifest, replace(rights, **change)
    ).reasons == ("rights_refused",)


def test_old_one_shot_or_deserialized_decisions_cannot_authorize_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _, manifest, rights = prepare(tmp_path)
    monkeypatch.setattr(admission, "_read_regular", never)
    monkeypatch.setattr(admission, "diagnose_in_container", never)
    old_manifest = PrivateSampleManifest.model_validate(
        {**manifest.model_dump(), "purpose": OLD_PURPOSE}
    )
    old_rights = RightsDecision(old_manifest.digest(), OLD_PURPOSE, "cleared", "synthetic-only")
    for untrusted in (
        None,
        asdict(rights),
        {"approved": True},
        old_rights,
        replace(old_rights, manifest_digest=manifest.digest(), scope=PURPOSE),
    ):
        assert evaluate_private_affiliation_diagnostic(path, manifest, untrusted).reasons == (  # type: ignore[arg-type]
            "rights_refused",
        )
    changed = manifest.model_copy(update={"acquired_at": "2026-10-02T00:00:00Z"})
    assert evaluate_private_affiliation_diagnostic(path, changed, rights).reasons == (
        "rights_refused",
    )
    for untrusted_manifest in (old_manifest, manifest.model_dump()):
        assert evaluate_private_affiliation_diagnostic(
            path,
            untrusted_manifest,  # type: ignore[arg-type]
            rights,
        ).reasons == ("manifest_refused",)


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "directory",
        "symlink",
        "parent_symlink",
        "fifo",
        "size",
        "digest",
        "relative",
        "traversal",
    ],
)
def test_only_bounded_regular_file_with_no_symlink_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path, data, manifest, rights = prepare(tmp_path)
    monkeypatch.setattr(admission, "diagnose_in_container", never)
    if kind == "missing":
        path.unlink()
    elif kind == "directory":
        path = tmp_path
    elif kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        path = link
    elif kind == "parent_symlink":
        link = tmp_path / "parent"
        link.symlink_to(tmp_path, target_is_directory=True)
        path = link / path.name
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif kind == "size":
        path.write_bytes(data + b" ")
    elif kind == "digest":
        path.write_bytes(b"X" * len(data))
    elif kind == "relative":
        path = Path("relative.norm-xml")
    else:
        path = tmp_path / ".." / tmp_path.name / path.name
    assert evaluate_private_affiliation_diagnostic(path, manifest, rights).reasons == (
        "file_refused",
    )


def test_one_verified_buffer_and_closed_counts_only_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, data, manifest, rights = prepare(tmp_path)
    diagnostic = diagnose(data, manifest.expectation())
    calls, exchanges = docker_double(monkeypatch, encode_output(diagnostic))
    read = admission._read_regular
    buffers: list[bytes] = []

    def read_once(path: Path, manifest: PrivateAffiliationDiagnosticManifest) -> bytes:
        result = read(path, manifest)
        buffers.append(result)
        path.write_bytes(b"different unverified bytes")
        return result

    monkeypatch.setattr(admission, "_read_regular", read_once)
    result = evaluate_private_affiliation_diagnostic(path, manifest, rights)
    assert result == PrivateAffiliationDiagnosticResult("diagnosed", (), diagnostic)
    assert len(buffers) == len(exchanges) == 1
    assert exchanges[0][1].endswith(buffers[0])
    assert set(asdict(result)) == {"status", "reasons", "diagnostic"}
    for forbidden in ("@", str(path), manifest.sha256, IDENTIFIER.value, "Fictional"):
        assert forbidden not in repr(result)
    assert calls[-1] == ("rm", "--force", "b" * 64)


@pytest.mark.parametrize("mutate", [False, True])
def test_read_is_capped_and_mutation_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: bool
) -> None:
    path, data, manifest, rights = prepare(tmp_path)
    docker_double(monkeypatch, encode_output(diagnose(data, manifest.expectation())))
    fdopen = os.fdopen
    bounds: list[int] = []

    class Reader:
        def __init__(self, descriptor: int, mode: str) -> None:
            self.source = fdopen(descriptor, mode)

        def __enter__(self) -> "Reader":
            self.source.__enter__()
            return self

        def __exit__(self, *args: Any) -> None:
            self.source.__exit__(*args)

        def read(self, bound: int) -> bytes:
            bounds.append(bound)
            result: bytes = self.source.read(bound)
            if mutate:
                path.write_bytes(b"X" * len(data))
            return result

        def fileno(self) -> int:
            return self.source.fileno()

    monkeypatch.setattr(os, "fdopen", Reader)
    result = evaluate_private_affiliation_diagnostic(path, manifest, rights)
    assert bounds == [MAX_BYTES + 1]
    assert result.status == ("refused" if mutate else "diagnosed")
    if mutate:
        assert result.reasons == ("file_refused",)


@pytest.mark.parametrize("fault", ["malformed", "overflow", "cleanup", "forged", "exception"])
def test_result_and_failures_cannot_disclose_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    path, data, manifest, rights = prepare(tmp_path)
    diagnostic = diagnose(data, manifest.expectation())
    output = encode_output(diagnostic)
    if fault == "malformed":
        output = b"private@example.org /private/path"
    elif fault == "overflow":
        output = b"x" * 4097
    docker_double(monkeypatch, output, fault=fault)
    if fault == "forged":
        forged = diagnostic.model_copy(update={"extra": "private@example.org"})
        monkeypatch.setattr(admission, "diagnose_in_container", lambda *args: forged)
    elif fault == "exception":

        def fail(*args: Any) -> Any:
            raise RuntimeError("private@example.org /private/path")

        monkeypatch.setattr(admission, "diagnose_in_container", fail)
    assert evaluate_private_affiliation_diagnostic(path, manifest, rights) == (
        PrivateAffiliationDiagnosticResult("refused", ("diagnostic_refused",))
    )
