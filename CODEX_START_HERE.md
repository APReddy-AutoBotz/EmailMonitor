# Codex implementation handoff

**Baseline:** 2026-10-08. **Current phase:** EM-001 reviewed/CI-verified in Draft PR #1; EM-002 reviewed/CI-verified in Draft PR #2; EM-003 offline source policy under review. Check the [status ledger](docs/22-implementation-status.md) before starting another task.

## Read order

Read [AGENTS.md](AGENTS.md), [charter](docs/00-product-charter.md), [PRD](docs/02-product-requirements.md), [architecture](docs/04-architecture.md), [tenant isolation](docs/05-multitenancy-and-access.md), [security](docs/11-security-and-threat-model.md), and [backlog](docs/16-delivery-backlog.md). Then read task-specific documents and [acceptance criteria](docs/17-acceptance-and-traceability.md). Do not treat every document as a request to implement every phase now.

## First prompt to use

```text
Implement EM-001 only in APReddy-AutoBotz/EmailMonitor.
Read AGENTS.md and CODEX_START_HERE.md, then the referenced baseline and EM-001 acceptance criteria. Inspect the current repository and preserve existing changes.

Create a reviewable scaffold for the agreed Python/FastAPI backend, React/TypeScript/Vite frontend, contracts, tests, and offline synthetic-fixture harness. Choose supported stable dependency versions, verify licenses and compatibility, commit lockfiles, and document exact tested setup commands. Introduce CI for checks that actually exist. The initial UI must clearly say that extraction is not implemented; do not fake live results.

Keep external network access, production source credentials, outbound email, external AI, and real-data tests disabled. Do not implement later backlog items, deploy anything, purchase services, or change repository visibility/licensing.

Run the documentation validator, schema/example validation, backend and frontend smoke tests, type/lint checks, and fixture checks available for this slice. Update docs/22-implementation-status.md and traceability with actual evidence. Open a PR with changes, test results, unresolved risks, and EM-002 as the next task. If something is blocked, complete independent scaffold work and report the exact missing prerequisite without inventing success.
```

## Subsequent task prompt

```text
Implement the next READY task in docs/16-delivery-backlog.md, one task per reviewable PR. Read AGENTS.md and the current status ledger. Confirm dependencies and acceptance criteria, then implement, test, and update documentation and traceability. Do not weaken tenant isolation or source/network controls to get a demo working. Report the task ID, checks actually executed, remaining gaps, and next ready task.
```

## Milestone sequence

| Gate | Outcome | Tasks |
|---|---|---|
| G0 | Reproducible scaffold and offline fixtures | EM-001 |
| G1 | Tenant foundation and protected network/source layer | EM-002–EM-004 |
| G2 | Complete fixture-driven keyword/URL extraction and review | EM-005–EM-010 |
| G3 | Export, UI, quotas, deletion and operations | EM-011–EM-014 |
| G4 | Approved real-source connector pilot and measured benchmark | EM-015–EM-016 |
| G5 | Commercial hosted/private release readiness | EM-017–EM-018 |

Task dependencies, not numeric order alone, decide readiness. Outbound outreach and external-AI features remain a separate future release.

## What is deliberately unresolved

Actual customer identity provider, hosting region, commercial contracts, permitted sources, live data permissions, paid API credentials, model vendor terms, and final pricing must be chosen before production. None prevent offline implementation. Use interfaces and safe disabled defaults, not fabricated credentials or blanket permission assumptions.

## Definition of a successful first product demonstration

Log in to tenant A; enter a keyword and the synthetic source; process all fixture results including two search pages, duplicate links, differing first/corresponding authors, a tooltip, and an absent email; show evidence and truthful unresolved counts; export permitted records; log in to tenant B and prove it cannot access A's job, contact, export, object or progress feed. Restart a worker and show no duplicate accepted contact or billing unit.

This demonstration becomes possible after the relevant G1/G2/G3 tasks, not from the documentation pack or EM-001 alone.
