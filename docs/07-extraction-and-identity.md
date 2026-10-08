# 07 — Extraction, author identity and evidence

**Baseline:** 2026-10-08. Core parsing is deterministic where possible. AI is optional future assistance, never the authority for invented facts or network permissions.

## Separate the concepts

1. Paper metadata and ordered authors.
2. Candidate email text actually observed in a source.
3. An association between a candidate email and one or more author identities.
4. Technical syntax/domain checks.
5. Source permission and permitted use.

These are separate objects/states. A valid-looking address can belong to a publisher's support desk. A correctly associated address can be old. A published address can be unsuitable for outreach. The system must preserve all these distinctions.

## Extraction waterfall

Use structured article metadata/XML when available → article author blocks and explicit correspondence text → `mailto`/public contact attributes → approved dynamic reveal → permitted text PDF → later optional OCR. Run expensive routes only when the selected fields remain unresolved. Do not claim Crossref always supplies author emails; metadata discovery and contact extraction are different functions [S08].

Article metadata precedence: explicit structured field tied to the article, then article DOM, then PDF. Keep conflicting observations with timestamps instead of silently overwriting. Publication date types (online, issue, accepted) must be labeled. Missing DOI/date/journal is null, not an invented default.

## HTML and interactive contacts

Decode HTML entities and `mailto` addresses; ignore subject/body query content as additional email candidates. Store original spelling and normalized address. `title`, `aria-label` or `data-*` is admissible only when the connector establishes that it is ordinary publicly exposed contact information, not a credential or unrelated hidden payload. Do not scrape entire script bundles for accidental secrets.

Associate only within author/correspondence blocks or other explicit identity evidence. Global regex over a page must not turn copyright/support, advertisements, cited references or reviewer contacts into paper-author records. Handle multiple candidate addresses without picking the first occurrence.

## PDF parsing

Download within policy/byte limits, verify type, hash bytes, and parse in a sandbox with bounded memory/CPU/page count. Extract text and coordinates without OCR first. Handle multi-column layouts, footnotes, superscript markers, line-wrapped addresses, ligatures and encoded text. Page numbers are 1-based in exported evidence; coordinates state units and page dimensions. Character spans and bounding boxes are evidence locators, not identity proof by themselves.

Keep correspondence markers attached to names; infer a match from proximity only as weaker evidence. The nearest name is not always the correct author. Scan enough permitted pages to find correspondence; early stopping must be recorded, and a page cap cannot be reported as `no email anywhere`. Password-protected/corrupt/unparseable files get explicit outcomes; no password cracking.

pypdf documents limitations including text order and scanned-image extraction [S06]. Default parser dependencies must pass license review; PyMuPDF/MuPDF require their separate dual-license decision [S07].

## OCR extension

Disabled in the core until EM-EXT-01. Trigger only when relevant pages lack extractable text. Render selected pages under bounded resources, record OCR engine/version/language and image region, and route uncertain characters to review. Do not automatically 'repair' `l/1`, `O/0`, hyphens or Unicode lookalikes into an accepted email. OCR-derived observations must remain distinguishable from text extraction.

## Author model and identity rules

Preserve full Unicode display name, ordered position, affiliation list, ORCID when explicitly present, and role assertions (`first`, `corresponding`, both, neither, unknown). Corresponding author can be absent or plural. Equal-contribution markers are not automatically correspondence markers. A group/consortium author is a valid type and may have no personal email.

Email local-part similarity, institution domain or name proximity alone cannot establish a strong match. Explicit 'Correspondence to [name]: [email]' and matching author markers are strong evidence. Official institutional profiles can support a later bounded enrichment association but must match institution/field/identity; common names alone are insufficient. Old and current affiliations are separate observations, not an error to hide.

One person may have several addresses; one group address may represent several people. Do not enforce one-email-per-person or one-person-per-email. Never merge two people merely because their names or shared mailbox match.

## Association states and evidence strength

`unmatched`: observed email, no established author mapping.
`needs_review`: a possible mapping with ambiguity or conflicting evidence.
`accepted`: mapping supported by explicit rules or reviewed evidence.
`rejected`: candidate is wrong/out of scope.
`suppressed`: excluded under tenant privacy/use policy.

Evidence strength labels: `explicit`, `supported`, `ambiguous`, `none`. Optional `heuristic_score` is 0–100 ranking, not a probability. `calibrated_probability` remains null until a held-out calibration study supports it; never label an uncalibrated score as accuracy or certainty. Store rule/model version and reasons for every decision. High score cannot override a suppression or source restriction.

Only accepted, current, export-permitted associations enter the default contact export. All article outcomes remain visible in a separate report. Human acceptance requires cited evidence; free-text address entry alone is not acceptable evidence.

## Email normalization and technical checks

Preserve raw address. Normalize Unicode safely and the domain using IDNA; do not indiscriminately lowercase a potentially case-sensitive local part. Store a separate conservative comparison key and flag normalization collisions. Do not strip plus-tags or provider-specific dots globally. Support international names; handle SMTPUTF8 addresses as explicit supported/unsupported cases, not corrupted ASCII.

Syntax status: valid/invalid/unsupported/unknown. Domain status: `mx_present`, `address_fallback`, `null_mx`, `nxdomain`, `temporary_error`, `not_checked`. A domain without MX can have SMTP address-record fallback; null MX explicitly indicates no mail service. DNS checks do not prove the mailbox exists. `delivery_status` defaults to `unverified`; no SMTP probing, test email or third-party verification call in P0. See RFC sources in document 20.

## Evidence record

Store organization, source and article IDs; original/final/canonical safe URLs; observed time; route; content hash; short necessary excerpt; DOM selector/span or PDF page/box; parser/connector version; source-policy revision; association rationale and any review actor/time. Retain raw source only where the policy permits, with limited TTL. An excerpt can still be personal/copyrighted data and follows the same access/retention rules.

A hash proves equality to fetched bytes, not the truth of the source or ongoing availability. Retained excerpt provides review context; where excerpt retention is not allowed, store a minimal locator/digest and require authorized re-fetch for review. Never claim expired evidence was reverified.

## Quality targets

Precision is measured on accepted author-email pairs; coverage is measured separately on articles and on sources with obtainable contacts. Include no-contact, wrong-author and ambiguous examples in ground truth. Report both automated and human-assisted results. Do not tune and evaluate on the same fixture set or manufacture confidence percentages. See document 14.
