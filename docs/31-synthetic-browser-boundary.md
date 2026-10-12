# 31 — Approved synthetic browser isolation diagnostics

## Boundary and approval

EM-004c adds a separately reviewed synthetic-only browser diagnostic stacked on verified EM-004b/documentation head 70d61230. The project owner explicitly approved the temporary per-container browser security profile on 2026-10-11. That approval does not enable production/live acquisition, broaden source permissions, grant persistent access or change host security. No local bubblewrap retry, privileged container, added capability, host network/IPC, Docker socket, secret mount or no-sandbox fallback is allowed.

The default API/CLI/UI and live/browser acquisition entrypoints remain unavailable. This diagnostic reveals a labelled synthetic marker, not contacts or author associations. Full EM-004 remains PARTIAL: controlled public-DNS/rebinding/egress evidence and remaining generalized browser/document controls are not certified by this fixture. EM-006 remains gated. No migration or deployment is introduced.

## Dependencies and profile

Dev-only Playwright 1.63.0 is pinned with pyee 13.0.1 and greenlet 3.5.6. The official immutable linux/amd64 Playwright Python image manifest is `sha256:96b39581c89131729a7ecb8d532314af54c7f9bcc7a61fe15c7a9e77602acf59`; its parent index is `sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0`. Registry headers and raw response hashes were independently verified. This version carries Chromium 153.0.8010.12; the guest verifies that version and explicitly selects `channel="chromium"` new headless mode and `chromium_sandbox=True` (the API otherwise defaults to disabling the sandbox). The official image defaults to root, so the diagnostic explicitly selects UID/GID 1000 instead.

The profile baseline is current official moby/profiles commit `2ceae35d351c156cb5a8efc0fdc4a08cf94569d8`, raw SHA256 `6416b47770785a41ac59073cdc77d9fe98517df2799dc83ef207e622de3053f6`. `seccomp-browser.json` preserves every baseline field and all 60 rules, including clone3 ENOSYS behavior and absence of io_uring permission; it appends two argument-unfiltered allow blocks naming clone/setns/unshare and separately approved chroot. The owner separately approved chroot for one controlled CI attempt after actual sandbox startup failed at its namespace filesystem-isolation helper. Current Moby filters out its baseline chroot rule when outer bounding capabilities are empty; Chromium’s private user namespace must supply the needed namespace-local privilege without an outer capability grant. This exception permits chroot attempts by all processes inheriting the container filter and cannot be restricted to a pathname by ordinary seccomp; kernel capability/path/LSM checks still apply. These syscall names are permitted for the Chromium namespace sandbox; flags are not restricted solely to CLONE_NEWUSER. It does not substitute Playwright's historical 2020 default for today's restrictions. Apache-2.0 license/modified-file attribution is preserved under scripts/isolation/licenses. Inventory hashes and semantic-delta tests guard accidental changes.

The diagnostic container uses network-none, all capabilities dropped, no-new-privileges, this scoped profile, nonroot identity, read-only root, no host mounts, private 128 MiB shared memory, bounded 256 MiB temporary filesystem, 512 MiB memory/combined swap, one CPU, 128 PIDs, 256 file descriptors and no core dumps. The build downloads only official pinned base/package artifacts; browser runtime has no external network. It never calls `playwright install` or modifies the host sandbox settings. Missing runner support fails closed with no fallback.

## Mediation and actual acceptance requirements

An untrusted browser process has no direct network route to the gateway, host API/database/broker, metadata or external sources. The reviewed host harness exchanges only bounded JSON frames through owned container stdin/stdout pipes. Gateway IP, port, CA, settings, credential headers, request bodies, network sockets and mutation commands are not available in that protocol. BrowserFixtureRequest admits only bounded identifiers, GET, document/fetch/xhr and a bounded URL. The server-side TLS gateway still validates exact synthetic hostname/path, actual literal loopback peer, CA/hostname, deadlines/bytes/redirects and authorization on each hop/release. The diagnostic callback admits only the declared tooltip browser route; production tenant-authorized assembly is not enabled.

The mediator limits 64 requests,8192-byte request frames and 32768-byte responses, accepts no source/caller credentials and forwards no cookies or response headers. Browser HOME/XDG config/cache and crash diagnostics use fixed guest-verified directories under the same bounded disposable /tmp tmpfs; original home and image root stay read-only. Guest/host output is bounded; reply writes are nonblocking and deadline-aware even when a guest does not read; the host enforces a 60-second conversation deadline and removes its owned container in finally cleanup. The guest tries synthetic Authorization/cookie headers; actual fixture-server receipts must contain only Host/Accept/Connection. Current source authorization can be supplied through existing TenantFixtureAuthorization; previous actual TLS/current-tenant SQL tests remain required, but the browser diagnostic itself does not claim a production worker identity or concurrent tenant-policy proof.

The actual separate browser job must prove:

- nonroot/zero capabilities/no-new-privileges/seccomp and loopback-only namespace; actual IPv4/IPv6 ENETUNREACH for documentation targets
- Chromium's own namespace and seccomp-BPF sandbox status and absence of sandbox-disabling command-line flags
- unmediated Chromium navigation to a reserved documentation address fails on its actual network path, before interception is installed
- a real browser click reveals only a synthetic marker; approved fetch obtains actual verified TLS fixture bytes through bounded IPC
- image/CSS/script/iframe/fetch/XHR/WebSocket denials, blocked service-worker registration (including Playwright’s resolved absent-registration result), zero registrations/workers and no worker request reaching the gateway, popup closure and cancelled download, with no retained worker/popup
- actual gateway/guest counters and credential-free source requests agree, then clean browser/container termination

Interception is defense-in-depth atop OS network-none, not the sole boundary. Documentation targets and declared synthetic fixtures are the only diagnostic traffic. Header/method policy tests and static configuration checks alone cannot prove browser execution. No local browser/container/sandbox has run; actual acceptance awaits independent exact-tree review, publication and exact-head CI.

## License and release limits

Playwright is Apache-2.0, pyee MIT, greenlet MIT AND PSF-2.0; typing-extensions remains the existing PSF-2.0 dependency. Lock inventory covers 63 Python/159 JavaScript packages. Installed wheels preserve driver/package LICENSE, NOTICE, ThirdPartyNotices and .LICENSE sidecars, including Node/WebP and MIT/ISC/BSD/BlueOak components. The bundled proxy-agent-negotiate 1.1.0 entry declares MIT but lacks its full license text. Browser/system/FFmpeg notices, complete image SBOM, vulnerability review and release attribution remain unverified release gates; no production image is distributed or deployed.

Primary sources: [Playwright Docker](https://playwright.dev/python/docs/docker), [sandbox launch API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox), [new headless mode](https://playwright.dev/python/docs/browsers#chromium-new-headless-mode), [current Moby profile](https://github.com/moby/profiles/blob/2ceae35d351c156cb5a8efc0fdc4a08cf94569d8/seccomp/default.json), [profile license](https://github.com/moby/profiles/blob/2ceae35d351c156cb5a8efc0fdc4a08cf94569d8/LICENSE). See [validation](../reports/em004c-validation.md).

### Pinned own-status assertion

The Chromium 153 Linux table reports Layer 1 Sandbox=Namespace, not Namespace sandbox=Yes. Diagnostic parsing requires the complete seven pinned name/value rows without duplicates/unknown values, affirmative PID/network namespaces and Chromium Seccomp-BPF, and Chromium’s own adequate-sandbox evaluation. Missing or negative status fails closed with bounded table/evaluation evidence. This UI describes Chromium’s expected renderer sandbox status; it does not replace the separately required OS namespace/network evidence or establish production isolation. An assertion-only correction after the consumed chroot attempt cannot trigger another expanded-profile run without fresh authorization.

### Browser versus kernel network evidence

The un-intercepted fixed documentation-address navigation must fail with the exact pinned Chromium ERR_ADDRESS_UNREACHABLE or ERR_INTERNET_DISCONNECTED code, never timeout/unknown error/HTTP success. Chromium can rewrite an unreachable socket error to its offline error when only loopback is present. This browser outcome does not prove which connect syscall or kernel errno it used; the independent actual IPv4/IPv6 socket checks establish ENETUNREACH. Both browser rejection and namespace/kernel evidence remain mandatory, and browser offline emulation is prohibited. Routine classification fixes preserve the approved security configuration.


### Serialized async fixture channel

The guest uses the public async Playwright API so its WebSocket refusal awaits close without re-entering the synchronous dispatcher fiber. A lock serializes each complete capped JSON request/reply exchange; only the owned stdin read runs in a thread. Cancellation or invalid input poisons the channel permanently, preventing reuse while an underlying read may still be pending. The host's absolute deadline and cleanup remain authoritative. Coroutine/owned-stream tests do not replace actual synthetic browser CI or establish production isolation.
