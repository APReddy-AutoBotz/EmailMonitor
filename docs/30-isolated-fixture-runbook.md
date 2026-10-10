# 30 — Partial real TLS and isolated parser diagnostics

## Scope and task boundary

EM-004b continues EM-004 on the verified EM-005 stack. It introduces a test-only actual TLS/socket fixture route and a separately reviewed disposable network-none parser diagnostic. It is not full EM-004: browser network/subresource controls and browser sandbox acceptance remain absent. EM-006 and dependent extraction tasks remain gated. Default API/CLI/UI, live fetch and browser entrypoints are still unavailable. No migrations, credentials/grants, paid services, source approvals or deployment are introduced.

The original local bubblewrap route remains stopped. This change neither retries it nor changes host security. A separate GitHub-hosted disposable CI environment is the documented fixture acceptance route; local tests do not invoke Docker or a sandbox.

## Actual fixture TLS gateway

`TLSFixtureGateway` requires Settings(environment="test", fixture_mode=True). A trusted immutable SyntheticEndpoint selects only one IPv4 loopback address, ephemeral port, test CA file and exact canonical paths. Logical URLs still require the single synthetic publisher hostname, HTTPS, canonical path and no userinfo/query/fragment. There is no production private-address switch, environment proxy inheritance, caller header API, cookie jar, resolver fallback, arbitrary endpoint or retry.

The gateway connects the literal fixture address, checks the actual peer before/after TLS, verifies the CA chain and logical hostname, and keeps one absolute deadline across connect/handshake/headers/body/redirects. Header framing is ASCII, capped at 8192 bytes and bounded fields; duplicate names, transfer encoding, missing/invalid lengths, unexpected compression/media, excessive/truncated body and denial statuses fail closed. Chunked responses are unavailable. Every redirect and final release reauthorizes through the supplied server-side permission callback. Existing TenantFixtureAuthorization remains available for current real SQL fixture-policy checks; the real-TLS tests use controlled callback changes; an additional real-PostgreSQL regression composes the actual TLS gateway with current tenant policy and cross-tenant/revocation denial. This new SQL test awaits actual integration CI. No production DNS/connection-time/public-egress claim is inferred from this deliberately explicit loopback exception.

Tests create ephemeral synthetic self-signed test certificates and keys only in a temporary test directory and remove them with normal fixture cleanup. They verify actual TLS hostname and untrusted-CA refusal, peer-pinned I/O, redirect policy checks, credential-free requests, no denial retries, bounded response/deadline failures and revocation before release. They never visit public websites or probe cloud metadata.

## Diagnostic parser and restrictive CI

`observe_fixture` requires the same test-only settings, accepts at most 64 KiB UTF-8 HTML and returns a digest, bounded visible-text observation and tag count. Scripts/styles stay inert data; visible text is capped at 16 KiB, with depth/tag limits. This is not contact extraction, author/email association, a PDF adapter, full MIME validation or an extraction benchmark. EM-007/008 dependencies/licenses remain separate work.

The parser-only workflow builds the official immutable Python 3.12.13 image with existing locked runtime dependencies. A whitelist Docker context excludes caches, virtual environments, Git history and unlisted files. The runtime has no host bind mounts or service/credential environment. The host orchestration script is CI-only and verifies Docker inspection evidence before running nonroot diagnostics:

- network `none`, only loopback interface, no added capabilities, all capabilities dropped
- default seccomp, no-new-privileges, read-only root, nonroot UID/GID 65532
- 128 MiB memory and combined memory/swap, 0.5 CPU, 32 PIDs, 64 file descriptors, disabled core dumps
- 16 MiB noexec/nosuid temporary filesystem; no privileged mode, host network/IPC, Docker socket, secrets or security-setting changes

The diagnostic records actual kernel IPv4/IPv6 network rejection for reserved documentation destinations only, zero effective capabilities, seccomp/no-new-privileges state, and inert byte observation. A second synthetic process deliberately exceeds only its container memory cap; acceptance requires actual OOMKilled and exit 137. CPU/PID/file-descriptor limits are configuration assertions, not separately benchmarked enforcement claims. A 30-second host deadline and finally cleanup remove each owned container. Missing kernel/container support fails the check; no privilege or sandbox fallback exists.

Run pure/TLS tests with the normal aggregate `scripts/check.sh`. The separate parser job runs `python3 scripts/isolation/run_parser_acceptance.py` on its disposable GitHub runner after independent review. Never point it at customer infrastructure. Actual parser isolation remains unverified until that exact-head CI job passes; static configuration tests are not OS evidence.

## Browser hold and release gates

Browser code and security profile are deliberately absent. Official [Playwright Docker guidance](https://playwright.dev/python/docs/docker) requires extra user-namespace syscalls for its supported Chromium sandbox route; [Docker default seccomp](https://docs.docker.com/engine/security/seccomp/) does not supply that route with dropped capabilities. No custom/unconfined profile, added capability, root browser, host IPC or no-sandbox fallback was used. A separately approved and independently reviewed browser environment is needed before implementation/execution.

Python's [PSF license](https://docs.python.org/3/license.html) and immutable image metadata are recorded in runtime inventory. Image-wide SBOM/system attribution/vulnerability review remain release gates; no image is distributed or deployed. See [validation evidence](../reports/em004b-validation.md) and [status ledger](22-implementation-status.md).
