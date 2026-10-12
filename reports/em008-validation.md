# EM-008 — Synthetic bounded PDF observations

## Candidate and predecessor

This candidate adds one reviewed parser dependency, an inert bounded stateless PDF adapter/model, deterministic authored fixtures, schema/example/negative tests and actual PDF assertions in the unchanged network-none parser CI. It does not add acquisition, APIs, tables, migrations, persistent grants, OCR, accepted associations or live/production enablement. [Runbook](../docs/37-offline-pdf-observation-runbook.md).

EM-007 checkpoint head 26622480e1f9d429906e2c861c55fe39b20cde91 and merge b1e9cba60885e745904814c43e7981fd2289e742 share reviewed tree 878e846205ecb6fa04c15a906a1abad68b26291c and exact f4e5db8f/26622480 parents. Its own five gates passed: [application](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38302346445), job 114988059493, 599 passed/no skips in 126.30s with one existing alias-body Pydantic warning; [controlled transport](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38302346329), job 114988059442, 12 passed in 55.57s; actual [browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38302346393), [parser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38302346375) and [docs](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38302346376) passed. PR12 remains Draft/unmerged. Prior EM-WARN-01 remains open; service/runner notices are separate from pytest warnings.

## Acceptance mapping

- Actual two-page PDF with raised author markers and later correspondence footnote: distinct first/corresponding facts, page 2 / anchor (50,110), actual full CropBox region
- Actual two-column correspondence blocks: two separate candidates and actual distinct column anchors; no nearest-name guess
- Actual WinAnsi Unicode name and split address: preserved name, exact adjacent source fragments, labeled reconstruction and unaccepted association
- Same-name instances retained unresolved; no-contact excludes support/reference addresses
- Actual encrypted/corrupt/image-only fixtures refuse; page-cap fixture remains partial with unseen page count; byte/fragment/character/decoded-stream/deadline/geometry/invisible-text negatives fail safely
- No socket/subprocess/OCR fallback; context-scoped tighter decoder/tree limits and external JBIG2 disabled
- Structural contracts plus intentionally stronger runtime relational checks; fabricated address/metadata/author/page evidence refused
- Official exact lock hashes, installed metadata and complete BSD/Unicode/source notices; no optional parser/rendering dependency chain
- Existing container boundaries and mandatory actual PDF/network/OOM proof remain unchanged

The initial pre-review snapshot passed 56 focused PDF cases without skips. Local rendering/inspection of all twelve pages across seven unencrypted valid fixtures found legible standard-font text, proper raised markers and no overlap/clipping; scanned fixture is intentionally image-only blank white, encrypted/corrupt inputs were not decrypted/rendered. Poppler font-cache warnings occurred; renderer is preexisting QA-only tooling. Intermediate development failures (missing explicit null metadata on refusal, field-validation exception/type annotations and formatting) were fixed before the focused successful run. That snapshot's normal aggregate passed 572 tests/83 explicit unavailable-service skips in 23.71s; a new fresh-empty locked installation passed 572/83 in 27.28s. Both completed docs/contracts, Ruff lint/format (105 files), strict mypy (103 source files), inventory 64 Python/159 JavaScript, frontend type/lint/one React test/build. All 36 changed files were byte-identical to the successful fresh copy before this evidence-only append. Tightening after earlier successful development checks added rejection-before-hash and explicit low-page correspondence/color regressions; those runs validate the pre-review source. At that snapshot, required actual application 655/no skips, controlled 12, existing browser, actual PDF/parser network/OOM and docs CI plus independent exact-tree review remain pending. No container, browser, privileged initialization or host/network configuration was executed locally.


## Text-state review correction

Independent source review found that pypdf visitor anchors omit text rise and horizontal scale: a displaced or collapsed domain could otherwise appear adjacent in the observation. The corrected simple-Tj profile refuses nondefault Ts/Tz/Tc/Tw state and adjusted/implicit TJ/quote shows. Nine actual-stream regressions exercise displaced/collapsed/scaled text, spacing, adjusted/implicit shows and an explicit default-state positive; unsupported input retains no provisional authors or candidates. This intentionally tightens supported layout coverage rather than estimating missing rendering geometry.

The corrected focused suite passes 65 cases/no skips. Normal aggregate passes 581/83 explicit unavailable-service skips in 29.81s; a fresh-empty locked installation passes 581/83 in 29.02s. Both complete all docs/contracts, Ruff lint/format (105 files), strict mypy (103 source files), inventory (64 Python/159 JavaScript) and frontend gates. Corrected parser/tests/runbook bytes match the successful fresh copy before this report append. Actual application 664/no skips, controlled 12, browser, PDF/parser network/OOM and docs CI plus corrected exact-tree independent review remain required. No container/browser/privileged/host-security execution was performed locally.

## Limits

This is the document-16 synthetic byte-parser foundation, not generalized acquisition or universal PDF layout coverage. Regions are deliberately coarse actual page boxes, not glyph boxes. Unknown/complex transforms/fonts/structure refuse or remain unresolved; no OCR repair, password workflow, technical mailbox test, accepted identity or contact export exists. Author/metadata observations remain separate from association/review and do not claim a held-out benchmark. Source/tenant authority and retained-data permissions belong to the trusted orchestration boundary, not a URL or parsed document. No container, privileged initialization or host/network security change was executed locally.
