# 88 — Open Access pipeline: truthful offline candidate

**Status:** local candidate on branch `feat/oa-truthful-pipeline` (based on `feat/open-access-connectors`). Offline fixtures only. No live network path, database, migration or tenant authority is added. See the [status ledger](22-implementation-status.md) for task states and the [roadmap](25-open-access-strategic-roadmap.md) for the product goal.

## Why this slice exists

A review of the OA-006…OA-011 preview pipeline found integrity defects that violate the [product invariants](../AGENTS.md) (evidence is mandatory; no fabricated contact evidence; role/identity separation):

| Defect (before) | Effect | Fix (OA-012) |
|---|---|---|
| Crossref and bioRxiv works were always paired with the PLOS fixture `PMC10293847` | Authors/addresses from one paper were exported under another paper's title and DOI | Each work uses only its own full text; otherwise `full_text_unavailable` with zero contacts |
| Europe PMC keyword route ignored the query and fell back to a fixed PMCID | Any keyword "found" the same article | Real search planner/parser (OA-013) maps keyword hits to PMCIDs |
| Hard-coded ORCID `0000-0002-1825-0097` on every Crossref/bioRxiv contact | Author 1's identifier attributed to author 2 | ORCID kept only when declared on that author in the article and the MOD 11-2 check digit is valid |
| Defaults: DOI `10.1371/...`, year `2026`, bioRxiv date `2026-01-01`, first author promoted to corresponding | Fabricated metadata and roles | Unknown stays `None`; undated preprints are skipped |
| JATS: any `<contrib>` with `<email>` marked corresponding | Role fabrication (BMC-style JATS lists every author's email) | Only `corresp="yes"` or a correspondence cross-reference asserts the role; none at all ⇒ unknown |
| JATS: affiliation text concatenated out of document order | `", Cambridge, UK 1Department of…"` | Ordered text model; labels dropped |
| JATS: trailing punctuation kept in addresses; DTD internal subsets/entities accepted | Corrupt addresses; entity-expansion exposure | Exact address trimming; internal subset and entity declarations refused |
| `deliverability_score` was the recency weight | Implied a mailbox check that never happened | Renamed `recency_score` (heuristic, not a probability); `technical_status = syntax_valid_not_mailbox_verified` |
| Random `uuid4` contact IDs | Not idempotent across runs/redelivery | Deterministic `oa-<sha256>` from source, article key and comparison key |
| `total_articles_scanned = len(contacts)` | Misreported coverage | Per-work `ArticleOutcome` list; scanned/full-text/unmatched counts are measured |
| Fixture addresses on real institutional domains (`ethz.ch`, `ac.kr`, `stanford.edu`, `ox.ac.uk`) | Conflicts with the synthetic-fixture rule | Moved to reserved `.example` domains |

## Pipeline

```text
query --route--> discovery (bounded, <=100 works)
  europe-pmc : keyword -> /search (OPEN_ACCESS:y AND IN_EPMC:y [+ PUB_YEAR]) -> PMCID
  openalex   : works -> ids.pmcid, else DOI -> Europe PMC DOI lookup -> PMCID
  crossref   : DOI lookup or search -> DOI -> Europe PMC DOI lookup -> PMCID
  biorxiv    : DOI lookup or date window + local keyword filter -> preprint JATS by DOI
-> filters (year, excluded journals)  => excluded_by_filter
-> own full text (Europe PMC fullTextXML or bioRxiv JATS)  => full_text_unavailable | failed
   - PMCID inside the XML must equal the requested PMCID; DOI must equal the work DOI
-> JATS observations (literal addresses + association basis + evidence excerpt + SHA-256)
-> role filter (corresponding | first | both | all), suppression, export readiness
```

Auto routing: `PMC\d+` → Europe PMC; DOI with prefix `10.1101/` → bioRxiv; other DOI → Crossref; anything else → Europe PMC keyword search. The chosen route and reason are returned (`source_used`, `route_reason`).

**Merged discovery (OA-021).** `source="all"` runs Europe PMC, OpenAlex and Crossref, merges works by PMCID then DOI (each article is fetched and parsed once; `found_in` lists every source that returned it), and keeps going if one source fails (`source_errors`). Each outcome reports `license_category` from the article's declared license URL; a missing license is `unknown`, never assumed open.

## Association basis (JATS)

| Basis | Meaning | Status |
|---|---|---|
| `contrib_email` | Address inside that author's own `<contrib>` | `needs_review` |
| `corresp_xref` | Note referenced by exactly one author via `xref ref-type="corresp"` (or a `fn-type="corresp"` footnote) | `needs_review` |
| `corresp_initials` | Shared note; parenthetical initials directly after the address match exactly one eligible author | `needs_review` |
| `corresp_name_proximity` | Shared/unreferenced note; exactly one eligible author's surname appears between the previous address and this one | `needs_review` |
| `sole_corresponding_author` | Unreferenced note and exactly one author carries a correspondence marker | `needs_review` |
| `unmatched` | None of the above; e.g. a lab mailbox in a note shared by two corresponding authors | `unmatched` |

Local-part similarity or institution domain is never used. Every basis remains reviewable; `needs_review` is an observation state, not acceptance.

## Export readiness

`outreach_eligibility` is computed per contact and is separate from extraction:

* `suppressed` — exact address (case-folded) or suppressed domain including subdomains.
* `needs_review` — unmatched author, group-author mailbox, disposable domain or invalid syntax.
* `eligible` — otherwise. Informational reasons (`free_mail_domain`, `publication_year_unknown`) do not block.

Instantly/Smartlead CSVs contain only `eligible` rows and remain formula-safe. Export is a file; nothing is sent.

## Offline fixtures

Synthetic, authored, reserved domains only: `fixtures/europepmc/search-crispr.json` (six hits including a subscription item and a PMCID without registered full text), `fixtures/jats/usher-base-editing.xml` (shared note split by initials, email ext-link on a middle author, equal-contribution footnote, editor contrib, unattributable lab mailbox, prompt-injection body text), and `fixtures/biorxiv/jats/10.1101_2026.03.14.584920.xml`.

## Single-document intake (OA-014, OA-015, OA-016)

For the "I already have this article open" workflow, an operator submits bytes they are permitted to read; nothing is fetched and links are reported, never followed.

| Kind (sniffed) | Parser | Association bases |
|---|---|---|
| JATS XML | `extraction/jats.py` (identifier taken from the document's own PMC/DOI `article-id`; refused if absent) | as above |
| Landing-page HTML | `extraction/citation_meta.py` — Highwire `citation_*`, DC, PRISM tags | `highwire_author_sequence` (email tag after its `citation_author`), `correspondence_block_surname` (mailto inside a block reading as correspondence, exactly one author surname), `unmatched` |
| PDF (text layer) | `extraction/pdf_contacts.py` — pypdf, first 3 pages (max 5), 400k characters | `pdf_correspondence_surname` (needs caller-supplied author names; surname between the previous address and this one on the marker line, or on a bare marker line directly above), `unmatched` |

Never reported: addresses in header/footer/nav/aside/form chrome, hidden blocks, script/style/template text, mailto links outside correspondence wording, PDF references sections. Cloudflare-style obfuscated addresses are counted and **not decoded** (decoding would defeat a site's anti-harvesting control). Grouped PDF notation such as `{a,b}@lab.example` and addresses wrapped across lines are counted as review notes and never expanded or rejoined. Encrypted PDFs are refused; image-only PDFs report `image_only` (OCR is a separate license/decision gate).

Preview endpoint: `POST /api/v1/organizations/{org}/open-access/documents?known_authors=A;B&target_roles=all` with the raw document as the body (no multipart dependency added). Size is checked from `Content-Length` before reading and again after (20 MB). The preview server parses in-process; production must run these parsers in the network-none parser worker (EM-008 boundary).

## Researcher rollup, role accounts and export presets (OA-017, OA-018, OA-019)

* **Researcher profiles** (`results/researchers.py`): observations sharing an address comparison key form one profile; two addresses join only when both carry the same in-article ORCID with a valid check digit. Names never merge people. Flags: `address_has_conflicting_orcids`, `address_used_under_different_names` (both block `eligible`), `multiple_addresses_linked_by_orcid`, `invalid_orcid_declared`, `no_author_association`. `activity` is from the latest observed publication year only (`active_recent` ≤1y, `moderate` ≤3y, `dormant`, `unknown`). `affiliation_changed` compares affiliations across the profile's own observations.
* **Role accounts** (`info@`, `office@`, `noreply@`, `*-lab@`, …) are valid addresses but not personal contacts: `needs_review` with reason `role_account`.
* **Presets** (`results/oa_exports.py`): `instantly`, `smartlead`, `lemlist`, `hubspot` (eligible rows only, one row per address) and `evidence` (every non-suppressed observation with basis, excerpt, SHA-256, eligibility reasons). Plus `researchers` (one row per profile) on the preview export endpoint. Column names follow each tool's common import template; operators may still need to map custom fields on import.
* **Formula safety change:** `results.render.safe_csv` refuses unsafe cells. The OA renderers now withhold the *whole row* containing such a cell and count it (`X-EmailMonitor-Rows-Withheld-Unsafe`), instead of failing the entire export. Values are never rewritten. Trade-off: a legitimate title beginning with `-`, `+`, `=` or `@` withholds that row; the evidence export count makes this visible.

Preview endpoints: `POST .../open-access/export` (`preset` = any of the above) and `POST .../open-access/researchers`.

## Operator screen (OA-020)

`apps/web/src/openAccess.tsx`, reachable as **Open Access** in the workspace navigation. Three tabs: *Search open access* (summary counts, every work with its outcome, addresses with link basis, export readiness and an evidence drawer showing excerpt, locator and document SHA-256), *Analyze a document* (PDF/JATS/HTML upload with optional known author names and page address), and *Researchers*. Discovery requires `source.acquire`; downloads also require `results.export`. Client-side checks mirror server bounds; the server stays authoritative. Uploads send their own `Content-Type` (the shared client now only defaults to JSON when none is given).

Local run (Windows, as verified): start `uvicorn emailmonitor.dev_server:app --app-dir services/backend/src --port 8000` and `pnpm --dir apps/web dev`, open the Vite URL, choose **Open Access**, search `CRISPR` with *All observed* authors.

## Commands and observed results

```sh
cd services/backend
uv run pytest tests/test_openaccess_orchestrator.py tests/test_jats_hardening.py \
  tests/test_europepmc_search.py tests/test_open_access_preview_api.py
```

Executed 2026-11-14 on Windows with the locked environment: see the status ledger for the exact counts recorded at each commit.

## Not implemented / gates (owner input required)

1. **Live API access.** No live transport exists. See [document 89](89-open-access-source-register.md) for the providers' published terms, limits and the concrete owner decisions. Europe PMC, OpenAlex, Crossref and bioRxiv are public APIs, but enabling them requires a source-policy approval record (purpose, rate limits, contact/User-Agent identity, retention) and a production egress path equivalent to the test-only protected gateway. Until then only fixtures run.
2. **Persistence.** Results are computed per request; nothing is stored, so tenant RLS, retention and deletion fences do not yet apply to OA results. Integration into the durable job/association tables (EM-005/009/011) is required before production use.
3. **Review workflow.** OA contacts do not enter the existing association review queue.
4. **Benchmark.** Association-basis precision is unmeasured; EM-016 must measure it on licensed/approved held-out articles.
