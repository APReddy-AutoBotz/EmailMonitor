# 30 — Partial real TLS and isolated parser diagnostics

## Historical EM-004b scope and task boundary

EM-004b continues EM-004 on the verified EM-005 stack. It introduces a test-only actual TLS/socket fixture route and a separately reviewed disposable network-none parser diagnostic. It is not full EM-004: browser network/subresource controls and browser sandbox acceptance remain absent. EM-006 and dependent extraction tasks remain gated. Default API/CLI/UI, live fetch and browser entrypoints are still unavailable. No migrations, credentials/grants, paid services, source approvals or deployment are introduced.

The original local bubblewrap route remains stopped. This change neither retries it nor changes host security. A separate GitHub-hosted disposable CI environment is the documented fixture acceptance route; local tests do not invoke Docker or a sandbox.

## Actual fixture TLS gateway

`TLSFixtureGateway` requires Settings(environment="test", fixture_mode=True). A trusted immutable SyntheticEndpoint selects only one IPv4 loopback address, ephemeral port, test CA file and exact canonical paths. Logical URLs still require the single synthetic publisher hostname, HTTPS, canonical path and no userinfo/query/fragment. There is no production private-address switch, environment proxy inheritance, caller header API, cookie jar, resolver fallback, arbitrary endpoint or retry.

The gateway connects the literal fixture address, checks the actual peer before/after TLS, verifies the CA chain and logical hostname, and keeps one absolute deadline across connect/handshake/headers/body/redirects. Header framing is ASCII, capped at 8192 bytes and bounded fields; duplicate names, transfer encoding, missing/invalid lengths, unexpected compression/media, excessive/truncated body and denial statuses fail closed. Chunked responses are unavailable. Every redirect and final release reauthorizes through the supplied server-side permission callback. Existing TenantFixtureAuthorization remains available for current real SQL fixture-policy checks; the real-TLS tests use controlled callback changes; an additional real-PostgreSQL regression composes the actual TLS gateway with current tenant policy and cross-tenant/revocation denial. This SQL test passed in the verified 226-test application CI run linked below. No production DNS/connection-time/public-egress claim is inferred from this deliberately explicit loopback exception.

Tests create ephemeral synthetic self-signed test certificates and keys only in a temporary test directory and remove them with normal fixture cleanup. They verify actual TLS hostname and untrusted-CA refusal, peer-pinned I/O, redirect policy checks, credential-free requests, no denial retries, bounded response/deadline failures and revocation before release. They never visit public websites or probe cloud metadata.

## Diagnostic parser and restrictive CI

`observe_fixture` requires the same test-only settings, accepts at most 64 KiB UTF-8 HTML and returns a digest, bounded visible-text observation and tag count. Scripts/styles stay inert data; visible text is capped at 16 KiB, with depth/tag limits. This is not contact extraction, author/email association, a PDF adapter, full MIME validation or an extraction benchmark. EM-007/008 dependencies/licenses remain separate work.

The parser-only workflow builds the official immutable Python 3.12.13 image with existing locked runtime dependencies. A whitelist Docker context excludes caches, virtual environments, Git history and unlisted files. The runtime has no host bind mounts or service/credential environment. The host orchestration script is CI-only and verifies Docker inspection evidence before running nonroot diagnostics:

- network `none`, only loopback interface, no added capabilities, all capabilities dropped
- default seccomp, no-new-privileges, read-only root, nonroot UID/GID 65532
- 128 MiB memory and combined memory/swap, 0.5 CPU, 32 PIDs, 64 file descriptors, disabled core dumps
- 16 MiB noexec/nosuid temporary filesystem; no privileged mode, host network/IPC, Docker socket, secrets or security-setting changes

The diagnostic records actual kernel IPv4/IPv6 network rejection for reserved documentation destinations only, zero effective capabilities, seccomp/no-new-privileges state, and inert byte observation. A second synthetic process deliberately exceeds only its container memory cap; acceptance requires actual OOMKilled and exit 137. CPU/PID/file-descriptor limits are configuration assertions, not separately benchmarked enforcement claims. A 30-second host deadline and finally cleanup remove each owned container. Missing kernel/container support fails the check; no privilege or sandbox fallback exists.

Run pure/TLS tests with the normal aggregate `scripts/check.sh`. The separate parser job runs `python3 scripts/isolation/run_parser_acceptance.py` on its disposable GitHub runner after independent review. Never point it at customer infrastructure. The scoped parser network/OOM diagnostic passed exact-head CI as recorded below; static configuration tests alone are not OS evidence.

## Verified publication evidence (2026-10-10; rechecked 2026-10-11)

[Draft PR #6](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/6) head `3f6c96b8298478f3ffc2318b1d22e931229466c4` has independently reviewed tree `5706432f1af7302892aa7e84ea109225dfc36ea4`. The actual CI checkout merge `11f256a22232d0fa9c05e706ed6b4d8170a91107` has that same tree and parents PR #5 base `1abaa3a79936671b8b8c47b9574268f59a8c917d` and this head.

[Application CI 38047608099](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38047608099) passed 226 Python tests without skips, including actual TLS/current-tenant PostgreSQL and four actual broker recovery tests, plus lint/format/strict types/inventory/frontend test/build. Two FastAPI/Pydantic field-alias warnings appeared during concurrent last-owner-removal testing (`source_id` and `organization_id`); the CI run is not described as warning-free. [Documentation CI 38047608092](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38047608092) passed.

[Parser CI 38047608171](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38047608171) recorded loopback-only interfaces, IPv4/IPv6 kernel ENETUNREACH `[101, 101]`, inert synthetic byte observation and actual container memory-limit `OOMKilled=true`, exit 137. Owned test containers were cleaned up. This establishes the scoped diagnostic network/OOM boundary, not CPU/PID enforcement benchmarks, full PDF/browser isolation or production certification. Full EM-004 remains PARTIAL and PR #6 remains unmerged.

## Historical EM-004b browser hold and release gates

Browser code and security profile are deliberately absent. Official [Playwright Docker guidance](https://playwright.dev/python/docs/docker) requires extra user-namespace syscalls for its supported Chromium sandbox route; [Docker default seccomp](https://docs.docker.com/engine/security/seccomp/) does not supply that route with dropped capabilities. No custom/unconfined profile, added capability, root browser, host IPC or no-sandbox fallback was used. A separately approved and independently reviewed browser environment is needed before implementation/execution.

Python's [PSF license](https://docs.python.org/3/license.html) and immutable image metadata are recorded in runtime inventory. Image-wide SBOM/system attribution/vulnerability review remain release gates; no image is distributed or deployed. See [validation evidence](../reports/em004b-validation.md) and [status ledger](22-implementation-status.md).


## Earlier synthetic acceptance checkpoint (2026-10-12)

The absent-browser statements above describe the preserved EM-004b snapshot, not the current stack. Reviewed EM-004f head7b4fb2ab/tree d5d1f2f passed [application475/no-skip](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38282248083) with one disclosed Pydantic alias-body warning, [controlled12/no-skip/no-warning](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38282248247), [browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38282248046), [parser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38282248047) and [docs](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38282248062). Actual parser evidence requires stopped+OOMKilled=true+137; exit137 alone never passes. The browser remains nonroot/network-none with its approved restrictive profile and Chromium sandbox enabled. The controlled transport additionally verifies actual DNS/literal IPv4/IPv6 TLS pinning, current tenant policy and strict topology cleanup. Its final browser selected-peer diagnostic requires a bounded successful-receipt correction and exact-head revalidation; full EM-004 remains PARTIAL/EM-006 gated meanwhile. See [current topology runbook](34-controlled-transport-acceptance.md) and [exact evidence](../reports/em004f-validation.md). No live-source or production activation is inferred.


## Verified synthetic/offline foundation

The corrected EM-004f source head2c29a8ad/tree3cd450db passed independent source/evidence reconciliation and all five exact-head CI jobs. Application477/no skips includes one disclosed organization_id field-alias warning; controlled12/no skips/warnings now asserts and logs both successful browser-selected fixture peers. Actual parser and browser boundaries remain affirmative, with stopped/OOMKilled=true/137, loopback-only parser/browser interfaces, kernel ENETUNREACH and enabled Chromium sandbox. The scoped document16 EM-004 criteria are verified in an unmerged Draft. This does not activate live sources or production; [current evidence/criteria mapping](../reports/em004f-validation.md) and [ledger](22-implementation-status.md) define the distinction. Documentation-only checkpoint CI remains required before bounded offline EM-006 starts.


## EM-013 shared admission checkpoint

Reviewed216a8c3b/treebb37d8e7 passed application1267/no skips, controlled13/no skips/warnings, actual keyboard UI1 and browser/parser/docs. The added controlled case demonstrates real source admission/spacing and another tenant's CPU/private-export progress while source I/O is held; prior DNS/TLS/current-policy/escape/owned cleanup boundaries remain required. Network-none guests retain affirmative sandbox/lo/errno101 and parser stopped/OOMKilled=true/137. The exact13-count correction adds no isolation relaxation. [Evidence](../reports/em013-validation.md) and [runbook42](42-offline-admission-runbook.md) define this scoped unmerged proof. The documentation checkpoint must pass its own six gates before bounded synthetic EM-014; no live/production activation follows.
