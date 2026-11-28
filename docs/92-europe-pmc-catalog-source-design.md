# 92 — Design: Europe PMC as its own catalog source (option B)

**Status:** scoping for a later slice (OA-030), 2026-11-28. Not implemented. It follows [document 91](91-open-access-persistence-design.md), which stored Open Access fixtures under the `synthetic-publisher` fixture source (option A), and is a prerequisite for any live Europe PMC use ([document 90](90-open-access-live-transport-design.md)). Rules: [AGENTS.md](../AGENTS.md).

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

## Tests (two tenants, real PostgreSQL)

* A tenant with only a `synthetic-publisher` policy cannot plan, run or export Europe PMC work, and the reverse.
* Revoking one source's policy hides only that source's batches.
* Upgrade from 0027 with populated OA rows: history is preserved, and only the declared catalog delta changes.
* Every pre-existing fixture journey still passes unchanged.

## Risks

* This is the largest cross-cutting migration since the tenant foundation. A missed literal could make one source's rows visible under the other source's policy, so review must check every replaced function body, as was done for 0027.
* It is forward-only. Rows written under widened CHECKs block later narrowing.
* It needs a stable local PostgreSQL (document 26). Docker Desktop on the development machine has stopped several times; CI remains the authority.
