# ADR 0007 — Installed controlled XML through an owned byte capability

Status: proposed code-only EM-012/015/017 composition; not deployment approval.

## Decision and trust roots

The installed service worker may opt into the existing three synthetic provider
routes. This does not approve a source policy, change the XML v1 extraction rules,
certify Elsevier, or activate credentials. The default remains authored HTML.

A trusted supervisor owns and verifies the preprovisioned controlled gateway and
its isolated topology. It lends its gateway pipe to a packaged launcher. Endpoint
binding of that pipe is a supervisor prerequisite: an inherited descriptor is
not independent evidence of a container identity. The launcher does not provision
networks or grant access. The existing owned topology acceptance must still verify
immutable images, host state, network isolation, and cleanup.

The packaged launcher owns a separate immutable installed service-image container:
UID 65532, read-only root filesystem, dropped capabilities, no-new-privileges,
resource limits, private PID/IPC namespaces, no devices, image volumes or host
mounts. The worker cannot see the host Docker Unix socket or filesystem. Merely
filtering inherited file descriptors in a same-UID host subprocess was reviewed
and rejected as insufficient confinement.

This trusted SQL service worker uses host networking solely to retain the existing
reference configuration's loopback PostgreSQL/RabbitMQ connectivity. It is **not**
a protected-egress or network-isolated worker. The protected gateway remains in its
separately verified owned topology and the parser remains network-none. Immediately
before worker startup a fixed bounded read-only prerequisite verifies local Unix
Docker context and privileged listener ownership, refuses every dockerd-owned TCP
listener (any port/address), and refuses missing or ambiguous evidence. This uses
privileged `ss` inspection only; it never modifies Docker, networking or host
settings. A trusted supervisor/host must not expose a proxy to Docker or change
listeners while the worker runs. Point-in-time listener evidence is not protection
against a hostile host administrator. Unsupported hosts fail closed.

A fixed installed container bootstrap privately duplicates stdin/stdout into the
framed channel, then redirects application standard streams before importing and
starting Celery. Docker attach carries only bounded protocol frames. One initial
bounded service-configuration frame is consumed once, never logged or supplied on
argv. Only synthetic disposable configuration is in this milestone's acceptance.
There is no later configuration-replacement command. The worker receives no
executable/import/image/container/transport selector. Supervisor-only immutable
service and parser image identities come from verified installation artifacts.
The launcher inspects applied image/profile/owner identity and owns both the
worker container and attach process. The supervisor owns gateway shutdown only
after the launcher has quiesced/reaped its worker and relinquished the pipe.

The channel has exactly two operations: acquire an exact registered controlled
provider request, and parse bounded bytes with a registered XML expectation.
Requests are strictly framed, canonical, size/deadline/callback bounded and
sequential. Existing gateway lifetime ceilings (64 commands and 524,288 output
bytes) remain finite: exhaustion is a failed session requiring supervised fresh
provisioning and durable recovery, never a hidden reconnect/counter reset.
Malformed, unexpected, incomplete or uncertain exchanges poison the
channel. There is no retry or fallback to in-process parsing, fixture byte reads,
unrestricted HTTP, or another identity.

The launcher reuses the protected provider protocol. Its current-authority and
resource callbacks round-trip to the SQL-owning worker. Every callback is bound
to the same request/binding; only one resource ticket can be active. The worker
uses current ServiceWork authority, source admission and execution lease. The
launcher has no SQL identity or human session. Gateway bytes never become source
permission. The worker revalidates response and parser observation against the
original acquisition/immutable registry before the existing commit fences.

Only the launcher starts parser containers, using an explicit immutable image ID
supplied by the verified supervisor, the existing network-none profile, fixed
command and byte protocol. No worker field can select an image or command. Each
parse must prove stopped/non-OOM/success state and remove its owned child; cleanup
failure is a failure and never replaces a primary failure. The legacy diagnostic
and private one-file parser paths retain their existing independent controls.

## Integration and schema

ServiceBindings gains an explicit closed profile; only that profile admits the
registered provider start routes. It does not modify existing policy approvals.
The installed worker constructs the real dispatcher and ProviderJourney from the
channel after a durable SQL claim. Parser capability injection is narrow and
worker-side expectation/response validation stays in parse_response. Default
workers and absent/broken channels refuse XML. Human review and CSV/XLSX continue
through the existing services; warnings, incomplete affiliation coverage and
technical/outreach statuses are unchanged.

No migration is planned: 0014 already grants scoped observation/discovery/source
resource authority. Actual SQL tests must establish this, and any demonstrated
missing privilege requires a reviewed forward migration, never editing 0014.
Configuration and packaged entrypoints are source changes, not persistent access
activation. Production, real IdP, live sources and source credentials remain off.

## Acceptance required

- Strict transport/registry/byte/image/profile refusal and cleanup/poison tests.
- Installed controlled keyword and direct-URL keyboard flows through actual SQL,
  broker, gateway and isolated parser, followed by normal evidence review and
  CSV/XLSX. No harness-injected ProviderJourney.
- Current principal/member/session/source revocation, cancellation/deletion,
  before/after acquisition/parse races, stale tenant/export refusals.
- Observation-commit crash recovery with no repeat acquisition/parsing or effects.
- Separate explicit XML policy, retained quality warnings, original HTML journey.
- Normal and fresh local gates; all inherited hosted exact-head gates. Local
  infrastructure skips remain skips. No merge or deployment is authorized here.
