# Contributing to EmailMonitor

Read [AGENTS.md](AGENTS.md), the [Codex handoff](CODEX_START_HERE.md), [backlog](docs/16-delivery-backlog.md) and [status ledger](docs/22-implementation-status.md) first. Keep changes to one ready task or a smaller justified slice. Preserve existing code and unrelated work.

## Workflow

Create a branch such as `feat/em-001-scaffold` or `docs/clarify-source-contract`. State requirement/test IDs and acceptance boundary. Update contracts, examples, tests, status and documentation together. Use an ADR for architectural deviations. Open a pull request with actual test evidence; do not mark a task complete from a screenshot or mocked response alone.

## Available documentation checks

```sh
python -m pip install -r scripts/requirements-docs.txt
python scripts/validate_docs.py
```

This checks the documentation pack and schema examples only. Application setup/build/lint/test commands are introduced and verified in EM-001. Do not invent command output or describe an unimplemented service as running.

## Data and access

Use synthetic examples on reserved example domains. No customer data, actual harvested emails, licensed PDFs, credentials, session cookies, confidential contracts or raw production logs in the public repository. Live sources require documented permissions and explicit test scope. Do not run extraction/sending as part of normal unit/CI tests.

## Review gates

Tenant isolation, protected egress, source-policy enforcement, evidence integrity, deletion fences, safe exports, dependency licensing and truthful completion are blocking requirements. A convenient shortcut is not a reason to disable them. Migrations must describe compatibility and rollback/forward-repair. New dependencies require version/license/security review.

No contribution grants a project-wide license that has not been selected by the repository owner. See [NOTICE.md](NOTICE.md).
