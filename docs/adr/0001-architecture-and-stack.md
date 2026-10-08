# ADR-0001 — Modular monolith and bounded worker architecture

Date: 2026-10-08. Status: selected design baseline; implementation unstarted.

## Context

The product needs web UI, tenant authorization, potentially slow search/browser/PDF work, durable jobs, review and export. It will serve many organizations, but a first implementation should remain understandable and supportable by a small team.

## Decision

Use a Python/FastAPI modular monolith with shared domain services and independently scaled/isolation-controlled workers. React/TypeScript/Vite is the frontend. PostgreSQL is durable state. Celery/RabbitMQ transports stage work; a transactional outbox and leases make replay safe. Use explicit source/fetch/parser/storage interfaces. Exact supported dependency/runtime versions are verified and locked in EM-001.

No vector database, autonomous browsing agent, Kafka, Kubernetes or independently deployed business microservices in the first release. Add infrastructure only for a demonstrated requirement. The browser/parser isolation boundary is required for security even though business logic remains a monolith.

## Alternatives and consequences

A single script is faster to prototype but inadequate for multiple users/organizations, source controls and recovery. Microservices add distributed contracts and operational cost before the workflow is proven. A Node-only implementation would duplicate mature Python parsing work. A second frontend server is unnecessary for this internal-style application.

Consequence: straightforward shared rules and migrations; workers can scale separately. Modules must remain disciplined to avoid a tightly coupled monolith. Versioned interfaces and tests are required. Revisit when measured load, independent teams or customer isolation requirements justify a split.
