# 91 — Design: persisting Open Access results in the durable job model

**Status:** implemented as a local candidate (OA-029, 2026-11-21) on `feat/oa-persistence`; see "Implementation notes" at the end for where the code differs from this design. It turns the "Persistence" row of [document 90](90-open-access-live-transport-design.md) into a concrete plan against the existing tables. Rules: [AGENTS.md](../AGENTS.md); tenancy: [document 05](05-multitenancy-and-access.md); pipeline: [document 88](88-open-access-pipeline.md).

## Goal

Europe PMC full-text JATS articles processed by the Open Access pipeline become durable, tenant-scoped observations. Their candidates enter the **existing** association review queue. Exports come only from retained, reviewed (`accepted`) associations. This slice stays offline: fixture gateway only, `settings.fixture_mode` required, no live transport.

Out of scope: search/discovery persistence (`excluded_by_filter`, multi-source `found_in`), OpenAlex/Crossref/bioRxiv, single-document intake (supplied bytes have no registered digest and need object storage), and switching the outreach presets (`results/oa_exports.py`) to read retained results.

## What the existing model requires (verified 2026-11-21)

* Extraction work runs through `execution_runs` / `execution_items` (0007), one item per input URL; `job_items` is for fixture probes only.
* The data chain is `jobs` → `discovery` → `article_observations` → `association_batches` → authors, candidates, evidence, associations → `result_contacts` / exports.
* Every source is pinned to `synthetic-publisher`: the CHECKs on `discovery.source_id`, `article_observations.source_id` and `execution_runs.source_id`, the source fences, and `PolicyProposal.allowed_hosts`.
* Article URLs are a closed list: the `article_observations` and `execution_items` URL CHECKs (0018), plus the per-URL digest table and per-route provenance branches in `guard_article_observation` (latest in 0025).
* Registered documents already have a precedent. 0013 keeps provider documents in `source_catalog.support->'provider_documents'`, read through `registered_provider_document(source, url)`.
* Candidates must arrive as `technical_status='not_checked'`, `delivery_status='unverified'`, `outreach_eligibility='not_assessed'`, with `association_status` either `needs_review` or `unmatched`. Eligibility and outreach fields are computed at export, never stored.
* Tenant context is transaction-local (`Database.tenant`, `set_config(..., true)`), and RLS uses `tenant_allowed`.

## Decisions for this slice

1. **Storage: reuse the existing tables (option A).** OA JATS documents are registered under `synthetic-publisher` as additional fixture documents with synthetic article paths (for example `https://synthetic.publisher.example/oa/PMC10293847.xml`). Each registry entry records provider `europe-pmc`, the PMCID, the canonical Europe PMC `fullTextXML` URL, the content digest and the licence URL. This is honest for an offline slice, because the bytes are committed synthetic fixtures served from the synthetic host. **Before live use, Europe PMC needs its own catalog source (option B)**, a cross-cutting migration of the source CHECKs and fences that is its own slice.
2. **Migration 0027 (forward-only):**
   * Add an `open_access_documents` registry in the `synthetic-publisher` catalog support.
   * Widen the two URL CHECKs and `fixture_acquisition_operation` (to `fetch_xml`).
   * `CREATE OR REPLACE guard_article_observation`, adding a branch for route `jats_xml`, parser `open-access-jats-v2`, statuses observed / no_contact / partial / unsupported. The branch requires:
     * the registered digest, as both `source_digest` and `content_digest`;
     * the Europe PMC canonical URL and the requested PMCID;
     * isolation profile `network-none-parser-v1`;
     * the lease binding, as for `article_xml`;
     * a running job.
   * Bump `service_schema_ready`.
   * Every existing predicate stays byte-identical.
3. **No `oa-<sha>` contact id in the database.** It is a tenant-independent hash of an address and would link people across tenants. Replay identity uses the existing tenant-scoped uuid5 ids. The OA id is recomputed only for in-memory preview output.
4. **No automatic acceptance** for `jats_xml`. Every association goes to human review, so exports never contain unreviewed rows.
5. **Association basis and strength** stay in the observation JSON and the evidence locator. The association rule version is unchanged, and strength starts as `ambiguous` (or `none` when unmatched), following the existing mapping.
6. **Licence flag (owner decision 2026-11-19, "allow but flag").** The retained results document must carry `license_category`, so reviewed exports keep the flag. This needs a results/Bundle field in the same slice.
7. **Parsing stays isolated:** the JATS bytes go through the network-none parser channel, as the `article_xml` route does.

## Write path

Each step runs in its own `Database.tenant` transaction:

1. `Ledger.create` with the client `Idempotency-Key`.
2. Discovery plan and execution start: one `execution_items` row per registered PMCID path.
3. The worker leases the item.
4. `OaExtraction.isolated_fixture`, modelled on `XmlExtraction`: fixture gateway, `Operation.XML`, isolated JATS parse, then the observation insert (an identical replay returns the existing row; a different document returns 409).
5. `Associations.derive` builds a deterministic batch; a replay keeps existing reviews.
6. `execution_finish` binds the batch.

At-least-once redelivery is a no-op at every step.

## Tests (new `test_oa_persistence_tenant.py`, real PostgreSQL)

* **Two tenants process the same PMCID.** Their ids differ, and the second tenant sees zero rows and gets `AuthorizationDenied` for the other's observation, batch, associations and results, through both runtime-role SQL and the API.
* **Replay idempotency.** A double process and an outbox redelivery give one observation, one batch, the same association ids, and an accepted review that survives. A mutated document returns 409.
* **Review gate.** Nothing is accepted automatically, exports contain only accepted rows, and `unmatched` rows appear only with `include_unresolved`.
* **Deletion barriers.** A purge or offboarding during a lease makes the commit fail. Expired or purged observations are invisible.
* **Policy without `retain_excerpt`.** Excerpts are stripped and nothing is accepted.
* **Provenance refusals.** An unregistered URL, a wrong digest, a wrong canonical URL or non-fixture settings are refused, and no socket is opened.
* **Parity.** The in-memory pipeline's (address, author position) pairs equal the persisted candidate/association pairs for every fixture.
* **Migration.** Upgrade runs twice, `service_schema_ready` holds, and runtime grants and `BYPASSRLS` are unchanged.

## Risks and follow-ups

* Option A labels these rows `synthetic-publisher`, so a `source_id` results filter cannot separate them; option B fixes that before live use.
* The JATS fixtures are synthetic (invented titles, 2026 DOIs, `.example` addresses, documentation test ORCIDs). Their DOIs use real publisher prefixes such as 10.1371 and 10.1038; move them to the reserved test prefix 10.5555 before pinning digests in a migration.
* 0027 is forward-only. Rows written under widened CHECKs block any later narrowing.

Local database: [document 26](26-tenant-foundation-runbook.md) "Local disposable container".

## Implementation notes (OA-029)

* **Migration `0027_open_access_fixture`.** It is generated from the live 0026 function definitions with exact, count-checked substitutions, so every existing predicate is unchanged.
  * Adds `registered_open_access_document` (owner-only, revoked from runtime) and the `open_access_documents` catalog registry, plus the paths in `fixture_routes` and `routes_by_operation` (`fetch_xml`, `extract_contacts`, `retain_excerpt`, `export_contacts`).
  * Widens the two URL CHECKs, `fixture_acquisition_operation` and `fixture_admission_claim`.
  * Requires `fetch_xml` for `jats_xml` visibility in `association_visible`, `publication_batch_state` and `retained_article_batch_current`.
  * Binds `jats_xml` in `retained_article_binding` and classifies it in `retained_observation_presence`.
  * Adds a `JATS_OBSERVATION_PROVENANCE` block to `guard_article_observation`: registered digest as source, content and acquisition digest; Europe PMC canonical URL; requested PMCID; provider; network-none profile; lease binding; excerpt flag; reasons; licence class; running job; no reuse. A registered Open Access path can no longer satisfy the HTML admission branch.
* **Sandbox parse.** `parsing/jats_protocol.py`, `parsing/jats_worker.py` and `parsing/jats_channel.py` run the JATS parser in the existing parser image with the identical network-none profile under a separate command. The reviewed `xml_channel.py`, `xml_protocol.py` and `xml_worker.py` are pinned by hash in another workflow and were left unchanged; the JATS channel reuses their helpers. The worker image file list gained the five JATS modules, and the import-closure test now includes the JATS worker.
* **Retained record.** `extraction/jats_retained.RetainedJats` names the provider `full_text_provider`, because the existing provider block refuses a non-null `provider` on unregistered Elsevier paths. A truncated author list is retained as `partial` with reason `authors_truncated`; addresses without any observed author are refused.
* **Licence class in reviewed results.** `result_contact_document` adds `license_category` for `jats_xml` rows only, read from the stored observation, so every other contact document stays byte-identical. `Contact.license_category` is optional and omitted when absent. CSV and XLSX exports gain an "Article licence" column only when an export contains such a row. The operator UI shows the licence on the contact row.
* **Database-level hardening after independent review (2026-11-28).** Rules that had been enforced only in Python are now also enforced in SQL:
  * The `JATS_OBSERVATION_PROVENANCE` block now also requires:
    * a licence class from the closed set;
    * exactly the `RetainedJats` top-level keys, compared in C collation, so no extra free text can be stored outside the excerpt rules;
    * string-typed excerpts;
    * keywords that are strings of at most 300 characters (Python truncates to the same bound);
    * reasons limited to `authors_truncated`;
    * candidate author positions that exist on the article.
  * `guard_association_record` (copied from 0021 with one added rule) refuses inserting an `accepted` association into a `jats_xml` batch (`JATS_REVIEW_REQUIRED`). Acceptance is possible only through the human review update path.
  * The catalog route appends are NULL-safe.
  * A unit test keeps the SQL key and licence lists equal to the Python model.
* **Not done in this slice:** keyword-search persistence, and option B (a separate Europe PMC source).
* **Fixtures.** The JATS fixture DOIs moved to the reserved prefix 10.5555 before their digests were pinned.

