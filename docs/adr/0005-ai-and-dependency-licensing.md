# ADR-0005 — Optional AI and deliberate dependency/commercial licensing

Date: 2026-10-08. Status: selected design baseline; final legal license remains owner decision.

## Context

Earlier discussion suggested Jev and PyMuPDF. The first product is extraction, not reply classification, and it will be offered commercially to multiple organizations. Public repository visibility and third-party code licenses affect distribution choices.

## Decision

The extraction core runs without an AI key or hosted model. Deterministic parsing/rules establish observed evidence; a future provider adapter may assist ambiguous decisions under explicit privacy/quality review. No assumed Jev pricing, latency or availability is a product dependency.

Use pypdf/pdfplumber as text/layout parser candidates after exact-version/transitive license review. PyMuPDF/MuPDF is not automatically installed or redistributed: its official documentation states AGPL/commercial dual licensing [S07]. This is a legal/architecture review gate, not a claim that commercial software can never use AGPL. Optional OCR renderers/engines/language packs, browser binaries, container images and storage components also enter the inventory.

Do not add MIT/Apache/other project license automatically, copy a proprietary license template as settled legal advice, or change the public repository's visibility. The owner must choose confidentiality and distribution terms before proprietary implementation is released. Dependency license obligations continue regardless of project license.

## Consequences

A small dependency matrix, lockfiles, SBOM, vulnerability/license checks and attribution are required. Exact versions, platform support and commercial terms may change and are rechecked during implementation. A commercially licensed optional parser can be enabled only when the deployment has valid rights. Dedicated hosting does not erase license or AI data-transfer obligations.

References: document 20, especially S07, S12, S13 and S19.
