# One scoped Elsevier sample validation

## Decision and attribution

Decision reference: `em015-elsevier-ccby3-single-sample-20261020`. This authorizes
one bounded private parser evaluation of one identified article representation.
It is not a corpus-wide source grant or a live ScienceDirect entitlement.

Iain Staffell and Richard Green (2014), “How does wind farm performance decline
with age?”, Renewable Energy 66, 775–786,
[DOI 10.1016/j.renene.2013.10.041](https://doi.org/10.1016/j.renene.2013.10.041).
© 2014 The Authors. Published by Elsevier Ltd.
[Creative Commons Attribution 3.0](https://creativecommons.org/licenses/by/3.0/).
Normalized XML supplied by the
[Elsevier Labs OA-STM-Corpus](https://elsevierlabs.github.io/OA-STM-Corpus/).
No sample modification is made by this evaluation; the normalized representation
was supplied by that corpus.

The independently reviewed article-level license metadata identifies CC BY 3.0,
and its specific reuse footnote permits reuse with credit. The same normalized
XML also retains legacy “All rights reserved” copyright wording. That conflict is
recorded rather than silently deleted or treated as a new license version. The
specific article license, reuse footnote and official corpus context support this
narrow evaluation decision; this is not a blanket legal certification. Required
credit, license reference and original notices remain preserved.

The immutable sample is
[SourceXML/S0960148113005727.norm-xml](https://github.com/elsevierlabs/OA-STM-Corpus/blob/0ed398ec9288fd8936a24f9486647ecfcbf2d972/SourceXML/S0960148113005727.norm-xml),
commit `0ed398ec9288fd8936a24f9486647ecfcbf2d972`, exactly 143976 bytes,
SHA-256 `7c0add248911ef4a442b5a0b9569c605bf47aee2ccfc1315bfba7bf25d1e2c25`.
The digest was established by a separate anonymous byte inspection, not by a
parser accuracy result. Acquisition retains the original bytes unchanged.

## Dedicated execution boundary

A separate workflow handles only PR 42's initial `opened` event, attempt 1, on the
same-repository `feat/elsevier-one-sample-validation` branch against the fixed
`feat/private-offline-sample-admission` base revision
`158c7db1005a3398604aeca4cd60fdaca176ce9b`. Both workflow and Python guards enforce
the scope. Checkout is bound to that event's exact head SHA and must be clean.
Reopen, synchronize, push, manual dispatch, rerun, fork, changed refs/base and
credential/proxy/TLS/Docker overrides, including `SSLKEYLOGFILE`, refuse. The existing seven synthetic
workflows and their acceptance predicates remain unchanged.

This is one initial-event attempt, not a durable global exactly-once guarantee.
GitHub duplicate delivery outside these guards would require a separate durable
ledger to exclude categorically. No such ledger or reusable live route is added.
There are no retries or fallbacks after acquisition or parser failure.

Existing owned curated-image preparation and network-none probing finish before
sample acquisition. Their synthetic-prerequisite packaging labels describe the
artifact qualification; they do not relabel the real sample as synthetic or make
the image a production service. A fixed anonymous HTTPS GET targets only the
immutable raw.githubusercontent.com path. All DNS answers pass existing public
address validation; a single selected literal address is connected, with exact
peer, system-CA hostname verification and TLS SNI. Redirects, alternate addresses,
proxies, cookies, credentials, compressed/chunked bodies and changed length/digest
refuse. The socket/read deadline is 30 seconds and an outer 40-second alarm also
bounds DNS and header stalls.

The temporary mode-0700 directory and mode-0600 file are outside the checkout,
archive and image build context. The existing private admission harness binds
current acquisition time, immutable provenance and exact digest to the scoped
trusted-Python rights decision. XML parsing occurs only in its unchanged
network-none worker with unchanged byte protocol and OS/resource restrictions.
The selected immutable owned image is checked during private profile verification.
No host XML parser, tenant route, queue, source grant, record retention, contact
export, outreach or external-resource dereference is introduced.

The runner retains its temporary-directory ownership reference across context
exit failures or termination. Outer-finally removal gets at most two attempts
within 30 seconds and verifies filesystem absence before owned container/image
reconciliation (separately bounded to 180 seconds). An unresolved private file or
Docker cleanup failure forces `cleanup_refused`; neither check substitutes for
the other. Success is
emitted only after cleanup verification, as status/reason enums and bounded
author/candidate counts. Neither raw XML nor observations, contacts, excerpts,
private paths, tracebacks or build/process output are printed or uploaded. No
sample is a public fixture, test artifact, cache entry or committed manifest.
Signal/finally cleanup has a bounded reconciliation budget; SIGKILL, VM loss or
other abrupt failure relies on disposal of the hosted ephemeral runner. Secure
physical erasure and cleanup after arbitrary infrastructure loss are not claimed.

## Evidence limits

A parsed result establishes compatibility only for these exact bytes and the
reported supported/unsupported outcome. Counts do not establish extraction
accuracy, correct contact identity or a representative benchmark. Missing author,
contact or profile support must remain an explicit gap, never a fabricated result.
The scope does not include unrelated corpus articles, commercial harvesting,
linked resources, public contact disclosure or live API access.

[Validation report](../reports/elsevier-one-sample-validation.md) separates pure
synthetic controls, local limitations, independent review and any eventual actual
one-sample outcome. The opened-only workflow cannot be casually retriggered after
a failure; any additional real acquisition would require a new scoped decision.
