# 14 — Test strategy, quality measurement and pilot benchmark

**Baseline:** 2026-10-08. No application or live-source benchmark results exist yet. All numerical gates below are proposed targets.

## Test layers

Unit: URL normalization, policy evaluation, state transitions, author-role rules, email normalization, evidence constraints, quotas and idempotency keys.

Contract: JSON Schema examples, generated API/OpenAPI parity, strict unknown-field rejection, enums and null semantics, event versions, typed connector outputs.

Database: migrations from empty and previous versions; RLS using non-owner runtime roles; composite foreign keys; pooled connection reuse; unique effect keys; review concurrency; deletion fences.

Integration: PostgreSQL/outbox/RabbitMQ replay; worker leases; source-wide throttles; storage authorization; export invalidation; session/member revocation.

Connector: offline synthetic HTML, pagination, DOM reveal, article metadata, PDFs and malformed documents; approved-source canaries are separate opt-in jobs.

E2E: organization login, keyword/URL job, progress, review, export, pause/resume/cancel, two-tenant boundaries, inaccessible sources and quotas. Accessibility and keyboard flows are tested, not assumed.

## Fixture coverage

The included fixtures seed static pagination, duplicate article link, different first/corresponding authors, multiple corresponding authors, dynamic tooltip and no-email article. They are synthetic and use reserved example domains. They are not proof of live extraction coverage.

Implementation must expand fixtures for cursor paging, load-more/infinite scroll, page loops, malformed content, obfuscated public addresses, multi-column PDFs, line-wrapped emails, encrypted PDF, scanned PDF (OCR extension), absent contact, support/reference addresses, same-name authors, Unicode, multiple affiliations, ambiguous identity, invalid/suppressed contact, source revocation and cancellation races.

Generate synthetic PDF fixtures during EM-008 using a reviewed generator; no real publisher PDFs are committed. Include text pages, correspondence footnotes, multi-column ordering, no text, and deliberately broken PDFs. The documentation-only pack does not include generated PDFs.

## Security matrix

Two organizations and at least three roles; forged tenant path/header/body; cross-tenant author/evidence link; stale membership; guessed artifact ID; manipulated cursor; queue payload mismatch; RLS owner mistake; pooled connection leakage; support grant expiry; object path traversal; unsafe URL/IP/IPv6/redirect/rebinding; browser subresource escape; XXE; PDF resource bomb; CSV formula strings; prompt-injection text; token-bearing URL; deletion during export; startup with forbidden test overrides.

Zero observed isolation/unsafe-egress failures is mandatory, not an acceptable average. Record tests actually run; no fake security badge.

## Pilot design

Start with a reproducible offline end-to-end sample, then obtain permission for approximately 1,000 articles across at least three structurally different real source families. Include different disciplines, dates and article layouts. This sample size is a planning target, not a result. Expand to additional approved families only after connector certification.

Keep development/tuning examples separate from held-out evaluation. Record how articles were selected and what was excluded. Include missing-email and blocked-source cases, not only easy articles. Two human reviewers independently adjudicate a subset and resolve disagreements; prioritize all ambiguous/error cases and a blinded sample of accepted pairs. Do not upload actual researcher data to this public repository.

## Metric definitions

| Metric | Definition |
|---|---|
| Enumeration completeness | Discovered eligible unique articles / auditable expected eligible articles for a bounded known result set; unknown when denominator cannot be established |
| Contact coverage, all inputs | Articles with at least one accepted corresponding-author email / all submitted eligible article inputs |
| Contact coverage, obtainable subset | Same numerator restricted to articles independently confirmed to contain an obtainable permitted contact / that subset |
| Author-email precision | Correct accepted author-email pairs / audited accepted pairs; adjudicated ground truth |
| Extraction recall | Correct recovered observable address instances / known observable eligible instances in audited sources |
| Role accuracy | Correct first/corresponding role assertions / audited role assertions |
| Manual review rate | Associations requiring manual review / candidate associations; also report articles requiring review |
| Cost per usable contact | All allocated acquisition/compute/license/review costs / unique usable accepted contacts |
| Staff time saved | Comparable manual minutes minus assisted operator/review minutes on same task criteria |
| Retry correctness | Duplicate durable result/usage effects under replay; required count 0 |
| Evidence completeness | Accepted associations with required current evidence/version fields / accepted associations |

Report separate source, route and language strata; do not hide a failing source behind an aggregate. Include source blocks, no-contact outcomes, browser/PDF cost and confidence intervals. A DNS/MX check is not the ground truth for author identity or mailbox delivery.

## Proposed release gates

Accepted author-email precision ≥98% on at least 500 blindly audited accepted pairs, with a 95% interval and lower bound ≥95%. If too few accepted pairs exist, expand the authorized sample; do not claim the gate from a tiny sample. This is a benchmark gate, not a per-record probability.

Evidence completeness 100%; tenant isolation, suppression violations and duplicate billing effects 0 in required tests. Compare coverage against a ≥60% initial planning hypothesis, but report it by source and define exclusions transparently. Low coverage can lead to narrowing the certified source scope rather than fabricating contacts.

Time/cost and review-rate thresholds are agreed with pilot customers after measuring their baseline. No guaranteed wall-time SLA for externally throttled websites. Proposed control-plane p95, cancellation and restore targets are tested on the published environment.

## Load, failure and recovery tests

At least two active tenants; 100k synthetic contact rows per tenant; 10 concurrent interactive users; mixed static/browser/PDF jobs; one slow/blocked source; worker termination before and after commit; broker outage; database transient error; duplicate event; revoked policy; quota exhaustion; storage failure; deletion while a worker is alive. Reconcile discovered/terminal/nonterminal counts and usage after recovery.

## Evidence report format

Run ID/date; code/connector/policy versions; environment/resources; source approvals reference; sample construction; input/eligible/blocked counts; per-source metrics and intervals; actual test command/output; reviewed error examples (sanitized); review effort; cost model; limitations; pass/fail for each gate; owner and next action. Save sanitized reports in the repository and real-data reports in customer-approved private storage.
