# Installed controlled XML runtime — validation record

Status: local implementation candidate; hosted acceptance outstanding. No merge,
deployment, production source, source entitlement, API credential or service login
activation is authorized by this record. Actual CI uses disposable synthetic roles.

## Baseline and source ownership

Accepted dependent baseline: Draft PR46, head
`713c517750bb98c5330b26292b2582cd4aef5676`, tree
`a361145aa11fb418db6e119d5351a9f8d3c7c787`. The prior worktree was preserved. A separate
checkout was reconstructed from retained content-addressed publication material;
its tree and original commit exactly matched GitHub before edits began.

## Design review

[ADR0007](../docs/adr/0007-installed-controlled-xml.md) records the trust roots.
Independent review rejected an initial same-host subprocess design: passing only
an anonymous descriptor does not prevent opening the host Docker socket. The
implementation now uses a fixed immutable installed service container,
without host mounts/socket, with explicit read-only Docker-exposure prerequisites.
The trusted SQL worker's host networking is not claimed as protected egress.
Gateway and network-none parser retain their separate isolated boundaries.

Independent source-level review approved the confined launcher/channel, bootstrap,
read-only exposure prerequisite, provider proxy and immutable parser lifecycle.
The reviewer independently passed 128 channel/parser/exposure/launcher tests plus
nine pipe/confinement tests. This is source evidence, not actual Docker execution.

The earlier host-subprocess unit tests were useful protocol evidence only. They
are not accepted worker-isolation or installed-container evidence.

## Early local receipts (not complete acceptance)

- Existing lifecycle/CLI regression suite: 83 passed after preserving the default
  constructor call shape. The initial run had ten test failures from the new
  unnecessary `None` keyword argument; no runtime lifecycle assertion was weakened.
- Closed profile/admission tests: 17 passed.
- New immutable parser owner tests: 43 passed; mocked controls only, not Docker.
- New read-only daemon-exposure tests: 37 passed; mocked privileged reads only.
- Frontend: 77 React tests, typecheck, lint and build passed at its first checkpoint.
- XML packaging wrapper tests: 57 passed at first checkpoint.

Final combined normal/fresh gates, actual SQL/broker/container/browser gates,
exact-tree review and exact-head hosted results remain required. Local skipped
infrastructure tests never count as actual execution. Later edits invalidate
unrepeated whole-candidate claims.

## Required actual proof and limits

The installed keyword and direct URL paths must demonstrate genuine service-role
SQL, broker delivery, protected controlled HTTPS acquisition, pinned network-none
XML parsing, normal evidence review and CSV/XLSX. Source policy approval remains
an explicit human step. XML v1 attribution and quality/partial warnings are unchanged.

Post-observation kill/recovery must use an actual owned worker-container kill and
fresh verified gateway session, with no repeated acquisition or parsing and once-
only durable effects. A kill is a recorded failed session, not graceful cleanup.
Inherited tenant, revocation, lease, retention/deletion and provider-race gates
remain required; additional service-specific race gaps must be stated explicitly.
