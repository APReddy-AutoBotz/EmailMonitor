"""Build one owned service image from the already verified installed archive."""

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from run_service_acceptance import (
    OwnedServiceBuilds,
    probe_source,
    validate_dockerfile,
    validate_smoke,
)
from service_artifacts import verify_service_archive

from artifacts import archive, materialize, read

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def installed_service_image(installed: Path, context: Path) -> Iterator[str]:
    # No host checkout, configuration, credentials or caches enter this context.
    paths = list(installed.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise RuntimeError("Installed service links refused")
    files = {
        path.relative_to(installed).as_posix(): path.read_bytes()
        for path in paths
        if path.is_file()
    }
    manifest = files["manifest.json"]
    verified = verify_service_archive(archive(files), manifest)
    runtime = json.loads(manifest)["runtime_distributions"]
    recipe = read(ROOT, "scripts/packaging/ServiceRuntime.Dockerfile")
    validate_dockerfile(recipe)
    materialize(verified, context)
    (context / "Dockerfile").write_bytes(recipe)
    (context / ".dockerignore").write_text("migrations\n", encoding="utf-8")
    owner = OwnedServiceBuilds(uuid4().hex)
    try:
        image_id = owner.build(context, 1)
        help_output = owner.smoke(image_id, 1)
        if not help_output.startswith(b"usage:") or len(help_output) > 8192:
            raise RuntimeError("Installed service CLI smoke failed")
        with owner.probe_budget():
            validate_smoke(owner.smoke(image_id, 1, probe_source()), verified, runtime)
        yield image_id
    finally:
        primary = sys.exception()
        try:
            owner.close()
        except BaseException:
            if primary is None:
                raise
            primary.add_note("Installed service image cleanup failed")
