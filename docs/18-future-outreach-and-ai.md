# 18 — Future outreach, AI and manuscript workflows

**Baseline:** 2026-10-08. All features here are deferred. They must not displace or delay the core keyword/URL extraction workflow.

## Expansion sequence

EM-EXT-01 adds optional bounded OCR after text/PDF quality is measured. EM-EXT-02 adds permitted institutional/repository/wider-web enrichment with explicit user scope. EM-EXT-03 adds saved recurring searches and freshness. EM-EXT-04 adds governed author outreach only after a separate release decision. EM-EXT-05 adds optional reply triage and manuscript intake.

## Outreach boundary

An extracted contact is not automatically approved for sending. Before any email: current source/use rights, recipient/jurisdiction/purpose review, suppression, contact frequency, sender identity/authentication, provider terms, campaign approval and deliverability controls must pass. Do not rotate mailboxes or IPs to bypass provider limits. Do not give an AI unrestricted permission to email every discovered contact.

Separate campaign/contact state from observed contact provenance. Record approved template/version, sender, purpose, source association, reviewer and send event. Unsubscribe/suppression must work across the customer's applicable campaigns and be rechecked immediately before dispatch. Handling of purchased/automatically collected lists requires legal review beyond a checkbox.

## Mailbox integration plan

Use provider-authorized OAuth/API notifications where supported; verify current API scopes/limits at implementation. Store tenant-scoped secrets and renew subscriptions safely. Support idempotent webhook ingestion, replay and reconciliation. Validate webhook signatures/tokens. No 150-mailbox polling or scaling claims are a requirement for the extraction product.

Associate reply threads primarily through Message-ID/In-Reply-To/References and campaign IDs, with an explicit fallback review queue. A classifier should interpret intent, not guess database ownership or tenant identity.

## Optional decision-provider interface

A provider adapter accepts a minimized, approved input and returns a typed decision with evidence references, abstention, provider/version, latency and errors. Candidate providers, including Jev, must be validated for availability, commercial terms, data retention/residency, supported schema behavior and actual quality. No vendor price, 70–500 ms latency or 98% accuracy is assumed from earlier discussion.

Use atomic flags where intents overlap: unsubscribe, automatic reply, interested, question present, manuscript/attachment indication, human review required. A reply can include both a manuscript and a question. Detect actual attachments from MIME/provider metadata, not solely from prose. Type safety ensures output shape, not semantic correctness.

AI cannot override source restrictions, tenant isolation, suppression or sending approval. Default is abstain/review for uncertainty. A private app calling an external hosted model must disclose the external data flow; a customer-owned API key does not make inference local. Provider errors go to a durable retry/review queue, not a guessed classification. Evaluate on consented/synthetic/redacted data with per-intent precision/recall and multilingual cases.

## Manuscript intake boundary

A future upload/attachment flow requires anti-malware scanning, file/type/size limits, quarantine, isolated parsing, access control and retention. Receipt acknowledgement must not imply submission acceptance, peer review or publication. Link to the customer's authorized editorial submission system rather than replacing editorial decisions. An incoming file is untrusted even from a known author.

## Separate approvals and contracts

External AI processing, live sending, mailbox scopes, scheduled monitoring, manuscript storage and editorial integration each need explicit release/configuration approval and tests. No API keys, mailboxes, subscriptions or campaigns are created by this documentation pack. Keep capability flags off until their complete release gate passes.
