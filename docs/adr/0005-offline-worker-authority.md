# ADR 0005 — Explicit synthetic worker authority until production identity review

Status: Accepted for the bounded offline EM-005 foundation only, 2026-10-10.

The durable ledger and broker transport can be exercised independently of protected source acquisition. A synthetic probe persists a diagnostic marker and uses a temporary, normally authenticated test session for one organization. Every claim/result/publication resolves current membership; operator authority remains creator-scoped. Queue events contain only bounded identifiers in the existing event contract. No broad session-minting capability or all-tenant worker grant is introduced.

The test harness accepts loopback dependencies and explicit test mode, and production activation is unavailable. This is a deliberate test-only architecture, not a claim that a user session is the production machine-identity design. Production principal issuance, credential configuration, verifier/process isolation and deployment authorization require later explicit review.

Consequences: real disposable broker failures can establish offline durability; they do not establish source network isolation, production identity, commercial charging or extraction UAT. EM-004's unmet full gate continues to block acquisition. All diagnostics and their fixture-only usage units are labelled accordingly.
