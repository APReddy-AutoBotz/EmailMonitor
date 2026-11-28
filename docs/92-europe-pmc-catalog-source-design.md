# 92 — Design: Europe PMC as its own catalog source (option B)

**Status:** design ready for implementation (OA-030), 2026-11-28. Not implemented. It follows [document 91](91-open-access-persistence-design.md), which stored Open Access fixtures under the `synthetic-publisher` fixture source (option A), and is a prerequisite for any live Europe PMC use ([document 90](90-open-access-live-transport-design.md)). Rules: [AGENTS.md](../AGENTS.md).

## Why

Today every durable row is pinned to one source. CHECK constraints, definer fences and Python literals all name `synthetic-publisher`, so Open Access rows cannot be told apart by `source_id`. That also means no tenant can hold a Europe PMC source policy (approval, limits, retention) separately from the synthetic fixture source. A live connector needs that separate, tenant-approved policy, plus results that state their real source.

## Measured footprint (2026-11-28)

* About 170 `'synthetic-publisher'` literals across 20 migrations, among them CHECKs on `discovery`, `article_observations` and `execution_runs`, the fences (`discovery_source_fence`, `association_parent_fence`, `result_filters_valid`), lifecycle, administration, service authority and export functions.
* 15 Python modules (planning, discovery, extraction, policy evaluation, results and others).
* `PolicyProposal` (`sources/policy.py`) only allows `execution_mode='fixture'` and the single host `synthetic.publisher.example`.

## Approach

1. **A catalog row `europe-pmc`** with `execution_mode='fixture'` first, closed hosts (`synthetic.publisher.example` for fixtures now; `www.ebi.ac.uk` only once the live path exists), and its own `routes_by_operation`. It is introduced as fixture-only, so this slice enables nothing live.
2. **Source-generic constraints and fences.** CHECKs become `source_id IN ('synthetic-publisher','europe-pmc')`, or a foreign key to `source_catalog`. Fences take the row's own `source_id` instead of a literal. Each replaced function is generated from its live definition with count-checked edits, as 0027 was.
3. **Move the Open Access registry** from `synthetic-publisher` support to `europe-pmc` support. Existing OA rows written under option A stay valid as history: their source stays `synthetic-publisher`, and there is no rewrite of retained evidence.
4. **Policy model.** `PolicyProposal` accepts the `europe-pmc` source with its own host set and limits (`LiveApiLimits` already exists). Tenants approve it separately; approval of one source never implies the other.
5. **Results.** `result_contact_document` reports the real `source_id`; source filters can select Europe PMC rows.

## Live inventory at 0027 (measured 2026-11-28 on a fresh database)

Most of the roughly 170 historical literals sit in superseded function versions. What is live at 0027 is listed below.

* **CHECK constraints (5):**
  * `discovery_source_id_check`, `article_observations_source_id_check` and `execution_runs_source_id_check`. These are to widen.
  * `source_resource_requests_source_id_check` (provider HTTP attempts) and `jobs_check` (fixture probes only). These stay synthetic-only.
* **Column defaults (2):** `article_observations.source_id` and `execution_runs.source_id`. They keep the synthetic default; Europe PMC writers pass the source explicitly.
* **Functions (16):**
  * **Job- or article-scoped** (derive the source from the job's `discovery.source_id` or the observation's own `source_id`): `discovery_source_fence`, `execution_read_fence`, `association_parent_fence`, `guard_article_observation`, `retained_article_binding`, `result_contact_document`.
  * **Organization-wide results and exports** (need a source argument, see the decision below): `results_fence`, `result_filters_valid`, `export_valid`, `publication_export_state`, `exports_create_pre_entitlement`.
  * **Privacy source suppression:** `privacy_canonical_allowed`, `privacy_source_allowed`, `privacy_source_state`. These are to accept `europe-pmc` as a suppressible source.
  * **Stay synthetic-only:** `delegate_service_work` (installed service path) and `source_resource_claim` (provider HTTP throttle). Open Access uses neither.
* **Python (about 12 sites):**
  * `discovery/planning.py`: `InputPlan` gains a server-chosen `source_id`; a registered Open Access URL gives `europe-pmc`. A client-supplied `source_id` that disagrees is refused.
  * `discovery/service.py`: `current_policy(..., plan.source_id)` and the discovery `INSERT`.
  * `extraction/jats_service.py` and `sources/open_access_documents.py`: the source becomes `europe-pmc`.
  * `fetching/fixture.py`: `TenantFixtureAuthorization` source allow-list.
  * `results/models.py`, `results/api.py`, `results/service.py`: the `source_id` literals.
  * `lifecycle/models.py`: source suppression.

## Decisions for OA-030

1. **Per-job source.** A job's source is the `discovery.source_id` that the server sets at plan time from the validated input, never a client authority. Job-scoped fences read it from the discovery or observation row; they no longer use a literal. At plan time, `discovery_source_fence` gains an explicit-source overload. The existing three-argument form resolves the source from the discovery row, defaulting to `synthetic-publisher` when the row does not exist yet (today's behaviour).
2. **One source per results or export request.** Results listings and exports are scoped by the filter's `source_id`. The default stays `synthetic-publisher`, so every existing request behaves exactly as before. Europe PMC rows need `source_id='europe-pmc'`, and only that source's approved policy (`extract_contacts`, `export_contacts`, `export_contacts_allowed`) gates them. No request mixes sources, so one source's policy can never release another source's rows.
3. **History stays valid.** Observations written under 0027 keep `source_id='synthetic-publisher'`. The synthetic catalog keeps the `/oa/` routes so that `association_parent_fence` still admits those retained rows. New Open Access work goes only to `europe-pmc`: migration 0028 moves `open_access_documents` to the `europe-pmc` catalog row, so `registered_open_access_document('synthetic-publisher', ...)` returns nothing and the guard refuses new synthetic-labelled Open Access inserts.
4. **Lock order.** Fences compute the source with a non-locking lookup first, then take their existing locks in the existing order. This adds no new lock ordering.

## Tests (two tenants, real PostgreSQL)

* A tenant with only a `synthetic-publisher` policy cannot plan, run or export Europe PMC work, and the reverse.
* Revoking one source's policy hides only that source's batches.
* Upgrade from 0027 with populated OA rows: history is preserved, and only the declared catalog delta changes.
* Every pre-existing fixture journey still passes unchanged.

## Risks

* This is the largest cross-cutting migration since the tenant foundation. A missed literal could make one source's rows visible under the other source's policy, so review must check every replaced function body, as was done for 0027.
* It is forward-only. Rows written under widened CHECKs block later narrowing.
* It needs a stable local PostgreSQL (document 26). Docker Desktop on the development machine has stopped several times; CI remains the authority.
