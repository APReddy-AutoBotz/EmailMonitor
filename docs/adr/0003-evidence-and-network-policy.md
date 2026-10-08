# ADR-0003 — Evidence-first extraction and governed network access

Date: 2026-10-08. Status: selected design baseline.

## Context

The user wants keyword or URL extraction across many publisher sites. Sites differ in structure and permission; researcher identity can be ambiguous; arbitrary URLs create security exposure.

## Decision

Separate discovery, protected acquisition, parsing, author-email association and use eligibility. Only observed addresses with explicit provenance can become accepted contacts. Keep first/corresponding roles separate, support plural correspondents and preserve unknowns. Heuristic evidence scores are not calibrated probabilities and DNS checks are not mailbox verification.

Use approved source connectors with bounded traversal and current source/purpose policy. All fetches, including redirects/browser resources, pass application checks and enforced egress. No unrestricted crawling, access-control bypass, proxy/identity rotation or hidden expansion beyond the user's selected source.

## Consequences

Some records/sources remain unresolved or blocked. That is preferable to fabricated contacts or unsafe/unlicensed collection. A generic parser is reusable, but a generic URL does not imply approval or perfect site coverage. Detailed completeness and stop reasons are part of the product's value.

Source approval, collection, personal-data processing, evidence retention, export and outreach are separate decisions. Raw documents are temporary unless retention rights allow otherwise. Revisit extraction rules through measured benchmarks, not vendor confidence claims.
