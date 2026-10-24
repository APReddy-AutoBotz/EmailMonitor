# Synthetic tooltip operator integration

## Existing requirements and boundary

This bounded EM-007/010/012 slice connects the already authored tooltip browser,
protected gateway, durable worker and review/export services. It is test-only
composition for `https://synthetic.publisher.example/tooltip.html`, not a general
browser runner or production activation. No schema, migration, endpoint, queue
payload field, dependency or live source grant is added.

Sources offers a separate closed HTML-plus-browser synthetic proposal. The
original HTML default and XML profile remain unchanged. The operator must
separately approve the actual pending record and explicitly select the initially
unchecked tooltip browser option when creating the job. Changing that option
invalidates the plan, including stale asynchronous planning/launch reads.

## Durable execution and authority

Only trusted Python composition injects the tooltip adapter into the ordinary
registered Celery task after its normal ID-only durable claim. All five configured
closure tasks are app-local (`shared=False`), so finalizing another worker cannot
substitute an earlier tenant/session/factory closure under the same task name. Default workers
retain truthful `requires_browser` results. Opt-out never invokes the adapter.
The bound execution lease, current source policy, job options, tenant and deletion
fences remain authoritative. Observations and association/effect accounting use
existing services; committed browser observations replay without acquisition.
Browser failures are not converted into static success.

The controlled adapter derives its source-policy version from the server's
prepared extraction row, rechecks current authority at gateway stages, allows
only the exact tooltip route and browser operation, and supplies real source
resource admission/completion. It does not use the older manual helper's fixed
policy version. The existing gateway, TLS/DNS checks, browser mediator and
network-none acquisition guest are unchanged. The UI uses a separate isolated
guest and ASGI relay. Neither guest receives database or broker credentials.

## Ownership and limits

One real solo worker exclusively owns the gateway pipe. Revocation covers the
whole browser conversation, including time in SQL callbacks. Readiness remains
bounded at 20 seconds, I/O at at most 20 seconds, join at 150 seconds and the
execution lease at 120 seconds. The existing browser conversation is 60 seconds;
its original three-second popup predicate and sticky failure are unchanged.

The topology precreates one inspected browser guest. This diagnostic composition
allows one actual attempt per guest and verifies its created state before launch
and exited/zero-status/no-OOM state before accepting evidence. A failed or
uncertain attempt poisons the pipe, requests a bounded stop of that exact owned
guest, and refuses reuse. The topology still owns final removal. A recovered
committed observation does not start the guest again. This deliberately does not
claim a reusable production browser pool or supervisor.

## Acceptance and remaining gates

A separate actual operator case must propose/approve the browser policy, opt in,
plan/start the exact URL, publish through the durable outbox and RabbitMQ, obtain
observed Elena Park evidence through protected HTTPS and the isolated browser,
review it and download CSV/XLSX artifacts, while another tenant is denied.
Require two HTTPS receipts, four DNS receipts, selected peers, enforced spacing,
finished source tickets, zero active resources, one durable effect and owned
cleanup. Existing static eight-second and provider 75-second waits are unchanged;
the new browser case has its own bounded wait for two spaced acquisitions and the
existing browser diagnostic.

Pure lifecycle/routing/UI tests and real SQL authority/replay tests complement,
but do not replace, actual controlled services. Normal/new-empty aggregates,
independent exact-tree review and all seven own-head workflows are required.
See [validation](../reports/operator-tooltip-validation.md). Real publisher
rights/samples, production identity/hosting/private storage/secrets and deployment
acceptance remain separate unmet gates.

The owned acceptance can record a bounded admission-timing diagnostic using its
existing tenant connection. Before gateway release it reads the exact active
ticket and matching tenant bucket under the fixed five-second policy, deriving
the SQL admission timestamp from `ready_at`. Only two ordinal observations and
clock intervals are reported, without ticket or tenant identifiers. The added
read perturbs timing; host monotonic and SQL epoch values are compared as separate
intervals. Diagnostic failure preserves ticket cleanup and fails completeness
after worker shutdown. The existing HTTP receipt-gap assertion, permissions and
all execution deadlines remain mandatory and unchanged.
