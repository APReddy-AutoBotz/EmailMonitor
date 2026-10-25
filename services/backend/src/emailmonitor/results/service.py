"""Current-authorized reads and transactional private synthetic export snapshots."""

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.cursor import decode, encode
from emailmonitor.results.models import (
    ArticleOutcome,
    ArticleOutcomePresence,
    Contact,
    ContactPage,
    EvidenceView,
    ExportInput,
    ExportPreview,
    ExportSnapshot,
    ExportState,
    Filters,
    OutcomePage,
)
from emailmonitor.results.render import Artifact, RenderDenied, render
from emailmonitor.runtime.access import WorkAuthority, WorkDatabase
from emailmonitor.runtime.delegation import ServiceBindings


def translate(error: DBAPIError) -> NoReturn:
    original = error.orig
    args = getattr(original, "args", ())
    data = args[0] if args else None
    code = getattr(original, "sqlstate", None) or (
        data.get("C") if isinstance(data, dict) else None
    )
    reason = getattr(original, "message", None) or (
        data.get("M") if isinstance(data, dict) else None
    )
    if (code, reason) in {
        ("EM011", "RESULT_SCOPE_DENIED"),
        ("EM013", "EXPORT_ENTITLEMENT_DENIED"),
        ("EM009", "ASSOCIATION_DENIED"),
        ("EM010", "EXECUTION_SCOPE_DENIED"),
    }:
        raise AuthorizationDenied() from error
    if code == "EM409" and reason in {"EXPORT_KEY_CONFLICT", "EXPORT_REVISION"}:
        raise RevisionConflict() from error
    raise error


@dataclass(frozen=True)
class Lease:
    organization: UUID
    export: UUID
    generation: int
    nonce: UUID
    snapshot: ExportSnapshot


class Results:
    def __init__(
        self,
        database: WorkDatabase,
        token: WorkAuthority,
        settings: Settings,
        *,
        bindings: ServiceBindings | None = None,
    ) -> None:
        require_fixture(settings)
        self.database, self.token, self.settings = database, token, settings
        self.bindings = bindings

    @contextmanager
    def _tenant(self, org: UUID, exporting: bool = False) -> Iterator[Connection]:
        capability = Capability.EXPORT_RESULTS if exporting else Capability.READ_ORGANIZATION
        try:
            with self.database.tenant(self.token, org, capability) as (connection, _):
                connection.execute(text("SELECT set_config('statement_timeout','5000',true)"))
                yield connection
        except DBAPIError as error:
            translate(error)

    def contacts(
        self, org: UUID, filters: Filters, cursor: str | None = None, limit: int = 50
    ) -> ContactPage:
        if not 1 <= limit <= 200:
            raise ValueError("Bounded page required")
        after = decode(org, "contacts", filters, cursor)
        with self._tenant(org) as c:
            rows: Sequence[object] = (
                c.execute(
                    text(
                        "SELECT emailmonitor.result_contacts(:org,CAST(:filters AS jsonb),"
                        ":first,:second,:limit)"
                    ),
                    {
                        "org": org,
                        "filters": filters.model_dump_json(),
                        "first": after[0] if after else None,
                        "second": after[1] if after else None,
                        "limit": limit + 1,
                    },
                )
                .scalars()
                .all()
            )
            items = tuple(Contact.model_validate_json(json.dumps(row)) for row in rows[:limit])
            last = items[-1] if items else None
            return ContactPage(
                items=items,
                next_cursor=encode(org, "contacts", filters, last.batch_id, last.association_id)
                if len(rows) > limit and last
                else None,
            )

    def outcomes(
        self,
        org: UUID,
        job: UUID | None = None,
        cursor: str | None = None,
        limit: int = 50,
        *,
        item_id: UUID | None = None,
        paper_doi: str | None = None,
        article_outcome_presence: ArticleOutcomePresence = "all",
    ) -> OutcomePage:
        if not 1 <= limit <= 200:
            raise ValueError("Bounded page required")
        filters = Filters(
            job_id=job,
            item_id=item_id,
            paper_doi=paper_doi,
            article_outcome_presence=article_outcome_presence,
        )
        after = decode(org, "outcomes", filters, cursor)
        with self._tenant(org) as c:
            rows: Sequence[object] = (
                c.execute(
                    text(
                        "SELECT emailmonitor.result_outcomes_filtered(:org,CAST(:filters AS jsonb),"
                        ":first,:second,:limit)"
                    ),
                    {
                        "org": org,
                        "filters": filters.model_dump_json(),
                        "first": after[0] if after else None,
                        "second": after[1] if after else None,
                        "limit": limit + 1,
                    },
                )
                .scalars()
                .all()
            )
            items = tuple(
                ArticleOutcome.model_validate_json(json.dumps(row)) for row in rows[:limit]
            )
            last = items[-1] if items else None
            return OutcomePage(
                items=items,
                next_cursor=encode(org, "outcomes", filters, last.job_id, last.item_id)
                if len(rows) > limit and last
                else None,
            )

    def contact(self, org: UUID, batch: UUID, association: UUID) -> Contact:
        with self._tenant(org) as c:
            row: object = c.execute(
                text("SELECT emailmonitor.result_contact(:org,:batch,:id)"),
                {"org": org, "batch": batch, "id": association},
            ).scalar_one()
            return Contact.model_validate_json(json.dumps(row))

    def evidence(self, org: UUID, batch: UUID, evidence: UUID) -> EvidenceView:
        with self._tenant(org) as c:
            row: object = c.execute(
                text("SELECT emailmonitor.result_evidence(:org,:batch,:id)"),
                {"org": org, "batch": batch, "id": evidence},
            ).scalar_one()
            return EvidenceView.model_validate_json(json.dumps(row))

    def preview(self, org: UUID, request: ExportInput) -> ExportPreview:
        with self._tenant(org, True) as c:
            document: object = c.execute(
                text("SELECT emailmonitor.exports_preview(:org,CAST(:request AS jsonb))"),
                {"org": org, "request": request.model_dump_json()},
            ).scalar_one()
            return ExportPreview.model_validate_json(json.dumps(document))

    def create(self, org: UUID, request: ExportInput, key: str) -> ExportState:
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 200
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in key)
        ):
            raise ValueError("Printable bounded idempotency key required")
        created = uuid4()
        with self._tenant(org, True) as c:
            export: UUID = c.execute(
                text(
                    "SELECT emailmonitor.exports_create(:org,:id,:key,"
                    "CAST(:request AS jsonb),:event)"
                ),
                {
                    "org": org,
                    "id": created,
                    "key": hashlib.sha256(key.encode()).hexdigest(),
                    "request": request.model_dump_json(),
                    "event": uuid4(),
                },
            ).scalar_one()
            if self.bindings is not None and export == created:
                self.bindings.issue(c, org, export, "export")
            return self._metadata(c, org, export)

    @staticmethod
    def _metadata(c: Connection, org: UUID, export: UUID) -> ExportState:
        row: object = c.execute(
            text("SELECT emailmonitor.export_metadata(:org,:id)"), {"org": org, "id": export}
        ).scalar_one()
        if row is None:
            raise AuthorizationDenied()
        return ExportState.model_validate_json(json.dumps(row))

    def state(self, org: UUID, export: UUID) -> ExportState:
        with self._tenant(org, True) as c:
            return self._metadata(c, org, export)

    def exports(self, org: UUID) -> tuple[ExportState, ...]:
        with self._tenant(org, True) as c:
            identifiers: Sequence[UUID] = (
                c.execute(
                    text(
                        "SELECT id FROM emailmonitor.exports WHERE organization_id=:org "
                        "ORDER BY created_at DESC,id LIMIT 200"
                    ),
                    {"org": org},
                )
                .scalars()
                .all()
            )
            return tuple(self._metadata(c, org, identifier) for identifier in identifiers)

    def revoke(self, org: UUID, export: UUID, revision: int) -> ExportState:
        with self._tenant(org, True) as c:
            c.execute(
                text("SELECT emailmonitor.exports_revoke(:org,:id,:revision,:event)"),
                {"org": org, "id": export, "revision": revision, "event": uuid4()},
            )
            return self._metadata(c, org, export)

    def claim(
        self, org: UUID, export: UUID, event: UUID, generation: int, seconds: int = 30
    ) -> Lease | None:
        nonce = uuid4()
        with self._tenant(org, True) as c:
            row: object = c.execute(
                text(
                    "SELECT emailmonitor.exports_claim(:org,:id,:event,:generation,:nonce,:seconds)"
                ),
                {
                    "org": org,
                    "id": export,
                    "event": event,
                    "generation": generation,
                    "nonce": nonce,
                    "seconds": seconds,
                },
            ).scalar_one()
            return (
                Lease(
                    org,
                    export,
                    generation,
                    nonce,
                    ExportSnapshot.model_validate_json(json.dumps(row)),
                )
                if row
                else None
            )

    def finish(self, lease: Lease, artifact: Artifact) -> bool:
        with self._tenant(lease.organization, True) as c:
            return bool(
                c.execute(
                    text(
                        "SELECT emailmonitor.exports_finish(:org,:id,:generation,:nonce,"
                        ":body,:mime,:extension)"
                    ),
                    {
                        "org": lease.organization,
                        "id": lease.export,
                        "generation": lease.generation,
                        "nonce": lease.nonce,
                        "body": artifact.body,
                        "mime": artifact.content_type,
                        "extension": artifact.extension,
                    },
                ).scalar_one()
            )

    def fail(self, lease: Lease, reason: str) -> bool:
        with self._tenant(lease.organization, True) as c:
            return bool(
                c.execute(
                    text("SELECT emailmonitor.exports_fail(:org,:id,:generation,:nonce,:reason)"),
                    {
                        "org": lease.organization,
                        "id": lease.export,
                        "generation": lease.generation,
                        "nonce": lease.nonce,
                        "reason": reason,
                    },
                ).scalar_one()
            )

    def process(self, lease: Lease) -> bool:
        try:
            artifact = render(lease.snapshot)
        except RenderDenied as error:
            self.fail(lease, error.reason)
            return False
        try:
            return self.finish(lease, artifact)
        except AuthorizationDenied:
            self.fail(lease, "snapshot_changed")
            return False

    def download(self, org: UUID, export: UUID) -> Artifact:
        with self._tenant(org, True) as c:
            row = (
                c.execute(
                    text("SELECT * FROM emailmonitor.exports_download(:org,:id)"),
                    {"org": org, "id": export},
                )
                .mappings()
                .one()
            )
            artifact = Artifact(bytes(row["body"]), row["extension"], row["mime"])
            if hashlib.sha256(artifact.body).hexdigest() != row["digest"]:
                raise AuthorizationDenied()
            return artifact

    def reconcile(self, org: UUID, export: UUID) -> None:
        with self._tenant(org, True) as c:
            c.execute(
                text("SELECT emailmonitor.exports_reconcile(:org,:id)"), {"org": org, "id": export}
            )

    def pending(self, org: UUID) -> list[dict[str, object]]:
        with self._tenant(org, True) as c:
            # Metadata selection grants no access; claim independently proves current scope.
            return [
                dict(row)
                for row in c.execute(
                    text("""
SELECT o.export_id,o.event_id,o.generation FROM emailmonitor.export_outbox o
JOIN emailmonitor.exports e ON e.organization_id=o.organization_id AND e.id=o.export_id
WHERE o.organization_id=:org AND o.published_at IS NULL AND e.state='queued'
AND e.generation=o.generation
AND e.expires_at>clock_timestamp() ORDER BY o.export_id LIMIT 200"""),
                    {"org": org},
                ).mappings()
            ]

    def confirmed(self, org: UUID, export: UUID, event: UUID) -> None:
        with self._tenant(org, True) as c:
            c.execute(
                text("SELECT emailmonitor.exports_confirmed(:org,:id,:event)"),
                {"org": org, "id": export, "event": event},
            )
