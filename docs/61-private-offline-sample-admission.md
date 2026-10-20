# Private offline sample admission

## Scope and prerequisite

This partial EM-015 step prepares a private, one-file Elsevier XML parser
validation boundary. It is not live ScienceDirect acquisition, source-policy
approval, a tenant API, a queue route, or contact persistence/export. Real sample
execution requires a separately established scoped rights decision and an
available reviewed Docker environment. No credentials or persistent access are
configured by this harness.

The [official Elsevier Labs corpus](https://elsevierlabs.github.io/OA-STM-Corpus/)
and [Elsevier dataset record](https://researchcollaborations.elsevier.com/en/datasets/an-open-access-corpus-of-scientific-technical-and-medical-content/)
provide a credential-free XML sample route for tool evaluation. Corpus-level
CC-BY statements do not resolve every article's legacy rights metadata or supply
an unobserved license version. A selected sample's unresolved rights evidence
must remain explicit and block admission until a scoped decision is established.
Do not infer live API entitlement from corpus access.

[Elsevier API guidance](https://dev.elsevier.com/tecdoc_text_mining.html) requires
an API key and distinguishes full-text entitlement. Its
[TDM policy](https://www.elsevier.com/about/policies-and-standards/text-and-data-mining)
distinguishes academic non-commercial access and other purposes. This harness
neither accepts agreements nor supplies those rights.

## Intended admission boundary

A strict host-side manifest records immutable source provenance, acquisition
time, byte length/digest, canonical article identity and expected XOCS profile.
An independent trusted-Python scoped decision binds the manifest; XML content or
a manifest field cannot authorize itself. Unresolved rights, changed bytes,
unknown fields or unsupported provenance must refuse before parser execution.

Read one bounded regular file, rejecting symlinks and nonregular sources. Verify
and frame the same in-memory bytes without parsing XML on the host or rereading
a potentially substituted file. The parser verifies article identity within the
isolation boundary. Its canonical API identity URL is not an acquisition receipt.

Existing synthetic fixture settings and worker guards remain synthetic-only.
A separately named private-offline admission guard is required; real input must
not be relabeled as a fixture. The reviewed Docker OS/resource limits and
xml-input-v1 framing/output schema remain unchanged. No fallback to host parsing,
bubblewrap, unshare, unrestricted containers or a live fetch is allowed.

Only fixed status/reason categories and bounded counts may leave the harness as
an evaluation summary. Names, addresses, affiliations, excerpts, document content,
private paths and raw exceptions must not appear in console output or public CI
artifacts. Real sample bytes/manifests stay outside Git; public tests are synthetic.

## Acceptance and remaining limits

Require refusal tests before Docker invocation, immutable-byte and identity
binding, original fixture/default-production refusals, adversarial output and
non-disclosure tests, bounded pipes and cleanup. Actual network-none CI must
exercise the distinct private entry with synthetic input and prove unchanged
kernel/resource restrictions. Mocked tests do not establish isolation.

Normal/new-empty aggregates, independent exact-tree review and all seven actual
own-head gates remain required. A successful synthetic private-entry check does
not establish a real sample result, real-source compatibility, extraction
accuracy, live entitlement or production readiness.

At initial inspection the current cloud workspace has no Docker/Podman/nerdctl
executable or daemon socket. Installed bwrap/unshare are not the reviewed backend.
No saved cloud coding environment is registered. No alternate machine is selected
or security setting changed. [Validation](../reports/private-sample-admission-validation.md)
records the actual checks and unresolved dependencies.
