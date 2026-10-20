# Retained article-quality review validation

Scope: additive EM-010/EM-012 current-authorized quality view and existing evidence/review drawer. See [runbook](../docs/65-observation-quality-review.md). No migration, production activation, parser association change or licensed source acquisition.

The separate observation-quality-v1 DTO leaves stored Bundle v1/input digests and derive replay unchanged. XML reasons remain fixed retained article-level facts. HTML reason availability is explicitly not recorded. Accepting author-email evidence cannot resolve missing affiliations.

Independent source review corrected an unnecessary runtime row-lock clause that required a privilege the runtime role does not have. The query now uses existing parent locks plus ordinary runtime RLS reads and a final visibility recheck. A dedicated keyed hook-owning child prevents pre-effect stale quality on refresh. Review also corrected inaccessible-resource test expectations to sanitized HTTP404 and added a test specifically exercising final runtime-join visibility loss.

## Required evidence

- Normal and genuinely new-empty Python/dependency aggregates, docs/contracts, Ruff/format, mypy, inventory, frontend peer/type/lint/57 component tests and build.
- Actual CI SQL/API tests for current authority, both tenants, no-contact access, retention/privacy denial and unchanged review/replay persistence.
- Actual isolated XML-to-database quality reads before/after review.
- Existing real keyboard operator journeys, now including XML quality presentation and held/failed/recovered HTML quality refresh.
- All seven synthetic workflows. Both unchanged exact-event PR42/PR44 licensed-source jobs must skip; no reacquisition or diagnostic repeat is part of this work.

Local service/container absences are skips, never credited as service acceptance. Exact-head CI receipts belong in the draft PR body after completion. This report records the validation boundary, not a claim that pending CI has passed.

## Preserved failure

An initial normal local aggregate reported 2960 passed, 311 skipped and one failure in the unchanged diagnostic pipe test: the short stderr child hit the existing 0.1-second deadline and returned affiliation_diagnostic_timeout where affiliation_diagnostic_failed was expected. All51 diagnostic-channel tests passed separately unchanged. The failed aggregate receipt is retained; no diagnostic timeout or control was relaxed. The later complete aggregates and actual Docker diagnostics remain required, and a successful repeat does not establish the timing failure's cause.

Rollback removes the additive route/model/panel/tests; there is no data migration or backfill. Drawer reachability remains contact-row based, so zero-candidate article-wide operator review is not completed by this slice. No general field-coverage, publisher certification, customer UAT or deployability claim follows from these checks.
