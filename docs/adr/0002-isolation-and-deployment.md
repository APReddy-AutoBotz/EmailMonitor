# ADR-0002 — Tenant isolation and deployment profiles

Date: 2026-10-08. Status: selected design baseline.

## Context

The user explicitly plans to supply EmailMonitor to many organizations. A single-tenant script copied into different folders would create support forks and make hosted expansion risky.

## Decision

All business data is tenant-aware from the first persistence task. Use server-side organization authorization, PostgreSQL RLS with non-owner runtime roles, composite tenant foreign keys, isolated secrets/objects/exports and tenant-scoped workers/events/caches. No cross-customer contact pool or automatic data reuse.

Support hosted regional cells and dedicated customer installations with the same images, schema and tests. Dedicated mode retains tenant checks. Strict database-per-tenant hosting is available as a deployment design choice when required, not an application fork. Organization branding/quotas/policies are configuration.

## Alternatives and consequences

Adding tenancy later risks overlooked background/export paths. One repository/fork per customer causes drift. Shared database RLS is economical but infrastructure admins remain privileged; contracts and operations must acknowledge that. Stronger physical isolation costs more and may be required by some customers.

Platform support is a separate identity with no default contact-data access. Customer-approved scoped access grants are audited and expire. See document 05 for exact role and lifecycle rules. Revisit shared/dedicated placement at contractual or measured scale boundaries.
