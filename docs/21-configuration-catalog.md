# 21 — Configuration catalog and safe defaults

**Baseline:** 2026-10-08. Numerical values are conservative starting proposals, not published provider limits or measured capacity. Final deployment values require tests and source/customer agreement.

## Override precedence

Effective permission is the intersection of platform safety, deployment constraints, source/license rules, tenant policy, plan entitlement and job request. For maxima, use the most restrictive limit. A plan upgrade or job setting cannot expand a source permission. Policy revocation applies immediately to queued/running work and exports. Record effective configuration and version per job.

## Job limits

| Key | Starting default | Enforcement |
|---|---|---|
| max_articles | 500 | Job cap, tenant cap may be lower; platform hard ceiling proposal 10,000 |
| max_search_pages | 100 | Stop with explicit incomplete enumeration; hard ceiling proposal 1,000 |
| max_link_depth | 2 | Only approved link types; hard ceiling proposal 5 |
| author_target | both | Enum corresponding/first/both/all |
| allow_pdf | true | Only where policy/connector supports it |
| allow_browser | true | Conditional on approved route and sandbox availability |
| allow_ocr | false | Extension gate, never a silent fallback |
| allow_wider_web | false | Separate scope/source approval |
| job_wall_seconds | 21,600 | Six-hour planning bound; resume/new continuation can be explicit |
| request_connect_seconds | 10 | Includes bounded DNS/connect handling |
| request_total_seconds | 60 | Total deadline, not reset by each streamed chunk |
| browser_unit_seconds | 90 | Hard bounded unit; cancellation fences writes |
| max_redirects | 5 | Every hop revalidated |
| html_max_bytes | 5,242,880 | 5 MiB streamed/decompressed bounds; reject oversized bodies |
| pdf_max_bytes | 26,214,400 | 25 MiB default; separate decompression/page resource caps |
| pdf_max_pages | 100 | Record truncation; don't assert no contact beyond inspected pages |
| max_attempts | 3 | Transient errors only; provider denial is not transient by default |
| repeated_no_new_pages | 2 | Report inconclusive/loop stop, not guaranteed exhaustion |

Production must implement additional parser memory/CPU/expansion caps after measured tests. A byte limit alone is not sufficient protection against malicious documents.

## Admission and quotas

Initial approved-source fallback limit proposal: 1 concurrent request and 0.2 requests/second per origin, with deployment-wide enforcement across tenants. Use a lower provider/license limit when applicable; honor Retry-After and account-wide limits. These are product defaults, not claims about any publisher's allowed throughput. Browser subrequests are included in source resource accounting and must not defeat the bucket.

Pilot tenant default proposal: 2 running jobs, 1 active browser unit, 5,000 article-resolution units per month, and explicit storage/export caps chosen at onboarding. No paid overage is charged without a contract. Usage reservations/reconciliation prevent oversubscription; jobs stop before exceeding hard limits.

## Retention and exports

| Key | Starting proposal | Notes |
|---|---|---|
| raw_download_ttl_hours | 24 | Lower/source-forbidden retention takes precedence; parser temp files shorter |
| evidence_excerpt_ttl_days | 30 | Minimal necessary permitted excerpt; no indefinite PDF archive |
| contact_observation_ttl_days | 90 | Renew only through authorized re-observation or reviewed policy |
| export_ttl_hours | 24 | Recheck current policy and record eligibility at download |
| audit_ttl_days | 365 | Minimal non-content audit; validate contractual/legal requirements |
| idempotency_ttl_hours | 24 | Durable business effect uniqueness outlives request-key cache |
| support_grant_max_hours | 4 | Scoped, customer-approved, immediately revocable |
| source_policy_review_days | 90 | Earlier license expiry/revocation overrides this interval |

There is no indefinite retention by default. A legal hold is a separately authorized, scoped exception with owner/review, not a role bypass. Backups need their own retention schedule and tombstone replay.

## Security switches

external_ai_enabled=false; outbound_email_enabled=false; wider_web_enabled=false; ocr_enabled=false. live_sources_enabled is false until protected-fetch and source approvals are operational. Generic unknown-source permission is always denied pending review.

No configurable option disables TLS verification, RLS, forbidden-network protection or source revocation in production. Test fixture transports and identity stubs are explicitly named test modes that production startup rejects, not unrestricted private-network overrides.

## Organization configuration

Display/legal name, logo reference, timezone, deployment region, identity-provider mapping, membership/capabilities, source policies/secret references, supported language preferences, retention and export purpose, entitlement/usage plan. Legal name/source permission cannot be inferred from branding.

Client settings control presentation only. API and workers share the validated effective configuration service and never trust an altered browser payload for quota, role, source permission or policy state.

## Configuration change tests

Reject unknown keys and inconsistent ranges; show effective lower limit; expire stale policy; enforce a reduced quota mid-job; revoke source while a browser is active; reject unsafe production flags; verify UI reflects but cannot override server restrictions; audit old/new versions without recording secrets.
