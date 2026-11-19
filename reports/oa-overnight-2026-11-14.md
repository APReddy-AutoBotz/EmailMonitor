# Open Access overnight work — handoff (2026-11-14 → 15)

**Branch:** `feat/oa-truthful-pipeline` (based on `feat/open-access-connectors`) · **PR:** [APReddy-AutoBotz/EmailMonitor#72](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/72) (draft)
**Scope rule followed:** database-free, offline, no live network calls, no new dependencies, no owner decisions taken. Details: [document 88](../docs/88-open-access-pipeline.md); provider terms and pending decisions: [document 89](../docs/89-open-access-source-register.md).

## What changed, in plain terms

1. **The Open Access pipeline no longer fabricates contacts.** Before: Crossref/bioRxiv results showed the PLOS sample paper's authors and emails under other papers' titles; keyword search always returned the same article; one ORCID/DOI/year was stamped on everyone. Now every address comes from its own article's full text with an excerpt and SHA-256, or the article is reported as "own full text unavailable".
2. **Keyword search works through Europe PMC** (keyword → PMCID → full-text JATS), plus OpenAlex, Crossref, bioRxiv and an "all sources, merged" mode that reads each article once.
3. **"I already have the article" workflow:** upload a PDF, JATS XML or saved publisher page (UI, API, or a batch command over a folder). Footer/header/nav/script/hidden addresses are ignored; obfuscated addresses are counted, not decoded.
4. **Publisher-oriented outputs:** researcher list (one row per person, never merged by name), role-account flags (`info@`, `office@`…), Instantly / Smartlead / Lemlist / HubSpot / evidence-audit CSVs, a "markup-only" high-precision option, license class per article.
5. **An Open Access screen** in the operator UI (browser-verified).
6. **Quality gates:** generated JSON contracts with a drift test, traceability rows, source register.
7. **Two independent code reviews** by fresh agents that tried to break the code: 17 defects found in round one and 13 in round two (including wrong-person attribution in "address (Name)" lists, surnames inside institution names, sliced non-ASCII addresses, and several denial-of-service inputs). A third round after midnight found 16 more (titles such as "Dr" read as initials, corresponding role spreading from shared e-mail footnotes, PDF line-wrapped addresses reported cut short). A fourth round found 7 more (co-author e-mail clauses, typesetting characters inside addresses, PDF wraps from the previous line, HTML link offsets). A fifth round checked that the stricter rules had not lost valid results and found 7 such losses (no wrong-person links). All 60 are fixed with regression tests (document 88 lists them), and the synthetic benchmark (18 documents) shows 27/27 correct links with no wrong-person, invented or missed addresses.
8. **CI unblocked:** since the first Open Access commit the `backend` and `installed-operator` gates failed before running any test because the service package hit a 256-file cap; the service package now has its own explicit 384-file cap (recorded in document 19 for your review). The `operator-ui` gate was already flaky before the Open Access work; on this branch it also hit Google Fonts that an earlier OA commit had added to the UI (a third-party request the isolated browser and the production CSP both refuse). The fonts are removed (system fonts now), four `transition: all` rules that animated visibility were made explicit, and a test forbids both. The gate now passes the plan, evidence and export captures and stops at the job-deletion capture (`capture_geometry_refused`) — the same refusal family (`capture_geometry_refused` / `capture_state_focus`) it showed on every sampled commit before any Open Access work. That harness is a pixel-redaction security control and was deliberately not loosened; it needs its own investigation.

9. **Safety nets added after midnight:** seeded fuzz tests that throw thousands of adversarial inputs at every parser and require each reported address to appear verbatim in the input; a 13-document synthetic benchmark of common publisher layouts that must show zero wrong-person links (it caught two more real defects, both fixed); a design note for live API access (document 90); and accessibility polish on the Open Access screen.

Also fixed along the way: the web lockfile had been downgraded from v9 to v6 by an earlier commit (broke the inventory gate); MeSH catalog had a wrong CRISPR descriptor ID; fixtures used real institutional domains and a real person's ORCID; the preview server claimed `live_sources_enabled: true`.

## Checks actually run (Windows, locked environments)

| Check | Result |
|---|---|
| Backend OA test modules (pytest, 20 modules) | 248 passed |
| Frontend `pnpm install --frozen-lockfile`, typecheck, lint, build | clean |
| Frontend `pnpm test` | 359 passed |
| `ruff check` / `ruff format --check` (CI target set) | clean |
| `mypy --strict` on changed modules/tests | clean |
| `scripts/validate_docs.py` | PASS |
| `oa_contracts --check` (drift) | no drift |
| Browser: search, evidence drawer, researchers, document upload, strength filter, attribution check | working, no console errors |
| GitHub CI on PR #72 | documentation, parser, browser, transport and packaging pass; backend/installed-operator were blocked by the package cap (fix pushed, CI re-running at hand-off); operator-ui fails as it did before this work; one parser failure was a runner memory-probe flake |

**Not run:** the full backend suite on this machine (Linux-only signals and PostgreSQL/RabbitMQ requirements); CI is the authority there.

## Decisions taken 2026-11-19

You accepted: Europe PMC as the first live source; OpenAlex deferred; a role mailbox for Crossref's polite pool (address still to be supplied); licences **allowed but flagged**; the 384-entry service package cap. The licence flag is implemented (OA-026: licence class on every contact and in every export, informational reasons that never block). Recorded in documents 19, 89 and 90. No live network access was built; that is the next slice and is described in document 90.

## Decisions originally waiting for you (status as of 2026-11-19 in document 19)

1. **Live API access** — approve or reject Europe PMC, OpenAlex, Crossref, bioRxiv for this purpose; choose a role mailbox for Crossref's polite pool; decide on an OpenAlex API key and monthly budget (keys are now needed for paging and usage is priced); confirm throttles (proposed in document 89; the current policy model enforces ≥5 s between requests). The engineering path once approved is in document 90.
2. **License stance** — whether contacts from articles whose license is `other`/`unknown` (e.g. some preprints) are allowed, flagged or excluded.
3. **Persistence** — OA results are computed per request; integrating them into the durable job/association tables (tenant RLS, retention, deletion) is the next engineering step and needs the database.
4. **Service package cap** — confirm the 384-entry cap (or prefer excluding preview-only modules from the service package).
5. **Merge target** — PR #72 targets `feat/open-access-connectors`; decide whether that branch should go to `main` or into the PR #70 integration branch.

## Next ready task

Persist OA discovery runs as durable jobs (EM-005/EM-009/EM-011 integration): store `ArticleOutcome` and contact observations under the server-authorized tenant, route them into the existing association review queue, and serve exports from retained, reviewed associations. Requires the PostgreSQL environment.
