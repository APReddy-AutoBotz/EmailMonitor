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

### Batch command line (OA-024)

For a folder of documents an operator already holds (no fetching, no recursion, no symlinks; ≤500 files of ≤20 MB):

```sh
cd services/backend
uv run python -m emailmonitor.discovery.batch_intake /path/to/articles --out /path/outside/repo/results.csv   --preset evidence --authors authors.csv --minimum-strength labelled
```

`authors.csv` (optional) has columns `file,authors` with `;`-separated names, used only to link PDF addresses. The command refuses to overwrite an existing output file, isolates per-file failures, and prints a per-file summary to stderr. The output contains contact data; keep it outside Git (`/exports/` and `/data/` are ignored).

## Researcher rollup, role accounts and export presets (OA-017, OA-018, OA-019)

* **Researcher profiles** (`results/researchers.py`): observations sharing an address comparison key form one profile; two addresses join only when both carry the same in-article ORCID with a valid check digit. Names never merge people. Flags: `address_has_conflicting_orcids`, `address_used_under_different_names` (both block `eligible`), `multiple_addresses_linked_by_orcid`, `invalid_orcid_declared`, `no_author_association`. `activity` is from the latest observed publication year only (`active_recent` ≤1y, `moderate` ≤3y, `dormant`, `unknown`). `affiliation_changed` compares affiliations across the profile's own observations.
* **Role accounts** (`info@`, `office@`, `noreply@`, `*-lab@`, …) are valid addresses but not personal contacts: `needs_review` with reason `role_account`.
* **Presets** (`results/oa_exports.py`): `instantly`, `smartlead`, `lemlist`, `hubspot` (eligible rows only, one row per address) and `evidence` (every non-suppressed observation with basis, excerpt, SHA-256, eligibility reasons). Plus `researchers` (one row per profile) on the preview export endpoint. Column names follow each tool's common import template; operators may still need to map custom fields on import.
* **Formula safety change:** `results.render.safe_csv` refuses unsafe cells. The OA renderers now withhold the *whole row* containing such a cell and count it (`X-EmailMonitor-Rows-Withheld-Unsafe`), instead of failing the entire export. Values are never rewritten. Trade-off: a legitimate title beginning with `-`, `+`, `=` or `@` withholds that row; the evidence export count makes this visible.

Preview endpoints: `POST .../open-access/export` (`preset` = any of the above) and `POST .../open-access/researchers`.

## Operator screen (OA-020)

`apps/web/src/openAccess.tsx`, reachable as **Open Access** in the workspace navigation. Three tabs: *Search open access* (summary counts, every work with its outcome, addresses with link basis, export readiness and an evidence drawer showing excerpt, locator and document SHA-256), *Analyze a document* (PDF/JATS/HTML upload with optional known author names and page address), and *Researchers*. Discovery requires `source.acquire`; downloads also require `results.export`. Client-side checks mirror server bounds; the server stays authoritative. Uploads send their own `Content-Type` (the shared client now only defaults to JSON when none is given).

Local run (Windows, as verified): start `uvicorn emailmonitor.dev_server:app --app-dir services/backend/src --port 8000` and `pnpm --dir apps/web dev`, open the Vite URL, choose **Open Access**, search `CRISPR` with *All observed* authors.

## Association strength (OA-023)

Every contact carries `association_strength`: **structural** (`contrib_email`, `corresp_xref`, `sole_corresponding_author`, `highwire_author_sequence` — markup ties the address to the author), **labelled** (an initials or name label/phrase does) or **none** (unmatched). Outreach presets accept `minimum_association_strength` (`labelled` by default, `structural` for highest precision); the evidence audit ignores it. Strength is an ordering, not a probability, and does not replace review.

## Independent review fixes (2026-11-14)

A fresh-context review of this branch reproduced 17 defects; all are fixed with a regression test each (`test_review_regressions.py`, `test_jats_hardening.py`, `openAccess.test.tsx`). The important ones:

* **Wrong-person attribution** in notes and PDF lines of the form `a@x (J. Smith), b@y (K. Jones)`: the surname window included the previous address's label. Shared helpers (`find_addresses`, `attribute_label` in `extraction/jats.py`) now let a trailing label decide alone (a label naming nobody ⇒ unmatched, never a fallback), and the preceding window starts after the previous label.
* **Absorption**: a note with several addresses no longer gives them all to its single xref/corresponding author; only a note's *sole* address inherits the structural owner, and only if no label names someone else. The HTML parser applies the same rule to several mailto links in one correspondence block.
* **Role fabrication**: a contrib email never marks correspondence; PDF `E-mail:`/`Contact:` lists (`pdf_email_line`, basis `pdf_email_label_surname`) label owners without asserting the corresponding role — only correspondence wording does.
* **Denial of service**: address finding is linear (bounded scans around `@`; over-long tokens are rejected, never sliced); the grouped/wrapped PDF detectors no longer backtrack; HTML block text is cached and at most 1,000 mailto links are inspected.
* **Robustness**: one malformed article (e.g. >100 authors, year 3025) becomes a `failed` outcome instead of failing the run; JATS keeps the first 100 authors with `authors_truncated`; Highwire tags after the 100-author cap are not attached to author 100.
* **Merging/linking**: multi-source merge joins groups bridged by a later record (no duplicate articles, no lost `found_in`); researcher profiles link addresses only through an ORCID tied by a structural basis and never through an address carrying two ORCIDs.
* **Smaller**: researchers CSV withholds unsafe rows (no 500); license classes require the creativecommons.org host; PMCID routing matches identifier bounds; addresses sort in document order past ten; group authors do not take members' addresses; author names keep `Surname, Given` in the UI.

## Second independent review fixes (2026-11-15)

A second fresh-context review attacked the first round's fixes and reproduced 13 further issues; all are fixed with regression tests (`test_review2_regressions.py`). Attribution now lives in `extraction/attribution.py`, shared by JATS, PDF and HTML:

* **Literal or nothing:** a token touching a non-ASCII letter (`müller@uni.de`), another `@`, or a run-on capitalised word (`x.edu.Phone`) is rejected, never sliced into a different address. Internationalised addresses are unsupported rather than corrupted.
* **A person, not a word:** unlabelled text attributes only through a person form (given name or initial + surname, or "Surname, Given"); a bare surname in running text ("Brown University", "Johns Hopkins", "de Medicina") never attributes. Labels attribute by exact surname, name form, or initials written as initials (upper case or dotted) — so `(Li)` is the surname Li, not initials L.I.
* **List direction:** "address, Name; address, Name" lists are read address-first; "Name: address" lists name-first; a name that already owns a labelled address is not reused.
* **Roles:** a Highwire `citation_author_email` and an HTML/PDF "E-mail:" line link an owner but assert no corresponding role (new bases `email_block_surname`, `pdf_email_label_surname`); only correspondence wording does. The HTML "E-mail:" marker now works.
* **Bounded time:** HTML block text is bounded (2,000 characters; longer blocks are page content, not correspondence lines) with linear caching; structured JATS addresses map to visible offsets linearly; at most 200 addresses per note are considered; the document identifier pre-scan is linear and falls back to the DOI when a PMCID is out of range.

## Regression safety nets (OA-025)

* **Seeded fuzz invariants** (`test_oa_invariants.py`): thousands of adversarial mixtures through `find_addresses`, `attribute_spans` and the JATS/HTML/PDF parsers. Every reported address must occur verbatim in the input; attributions name only known people and only when their surname or initials appear; hostile input raises only `FetchDenied`.
* **Synthetic association benchmark** (`fixtures/oa-benchmark/`, `python -m emailmonitor.discovery.oa_benchmark`): 13 annotated documents modelled on common layouts (PLOS xref, BMC all-author emails, Frontiers "Name, address", MDPI initials footnote, eLife separate notes, consortium member + data mailbox, institution-word trap, Highwire tags, correspondence block, address-first e-mail line, PDF correspondence/e-mail lists, non-ASCII address). It scores wrong-person links, invented/extra addresses, role mismatches and misses per link basis; `test_oa_benchmark.py` requires zero of each. On its first run it found a real defect — an unreferenced "Data requests" note was given to the sole corresponding author although the article links its notes by markup — and a completeness gap (a consortium member's own address was not reported). Both are fixed. This corpus is authored and synthetic: it guards regressions and does **not** measure real-world precision (EM-016 must use approved held-out articles).

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
