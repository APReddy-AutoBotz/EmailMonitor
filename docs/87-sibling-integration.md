# Local sibling-Draft integration candidate

This local-only FR-006/020/021/025/029, NFR-011 and EM-009/012/014 candidate
reconciles selected product behavior from Drafts 58, 61 and 62 on top of the
accepted Draft 67 source `07a3e2f77ea7c202ef17468a2c415ed82dbb3ed0`.
No Draft is merged or closed; no source grants, credentials, production access,
acquisition mode, database migration or deletion of real data is introduced.

## Source comparison and choices

- **PR58:** current PR67 has the existing server history endpoint and current
  batch and contact authorization, but no recorded-history panel. The local
  candidate carries that panel and its tenant/revision/retention fences. The
  newer audited `unlink` action is explicitly displayed; malformed history is
  unavailable rather than rendered. The synthetic check-shell helper now starts
  its own session and, on timeout, signals only that owned process group. Tests
  check success, timeout, already-gone and cleanup-refusal behavior; an uncertain
  signal or reap retains the original timeout and records fixed uncertainty.
  This is test machinery, not product process management.

  PR67's parser stage receipt already identifies build, parser, OOM and complete,
  preserves the original result and is covered by controlled-double tests.
  PR67 additionally waits up to two seconds for the daemon's OOM event and
  still requires a stopped container, actual `OOMKilled=true` and exit 137.
  Pure tests cover each failed condition and owned cleanup. The older extra
  `oom_flag_absent_exit137` check-metadata category is not byte-equivalent and
  is deliberately not copied: it adds no acceptance evidence when there is no
  actual OOM and no current failure requiring a further metadata split. Stage
  metadata alone does not establish which OOM-state check failed.
- **PR61:** current PR67 has the existing lifecycle API but lacks the
  selected-job staging UI. The local candidate carries explicit owner capability,
  a selected-job-only reason and confirmation, job reread, scope/revision fences,
  verified receipt and uncertain-outcome handling. It does not invoke purge or
  backup replay. The UI warns that the server invalidates existing exports across
  the organization. The older fixed XML export-subphase metadata is already
  present in PR67 in the expanded `guest_outcome.py` and `xml_progress.py`; PR67
  also retains a later bounded publisher snapshot. This is behavioral overlap,
  not a claim that the independent historical XML failures were repaired.
- **PR62:** current PR67 has plan/start APIs and the newer plan-summary UI but no
  saved-draft continuation component. The local candidate preserves the same job,
  rechecks current permission and job revision, shows the current plan summary,
  rejects unpersisted or unsupported plans, and submits a reviewed launch at most
  once. It keeps plan state outside the resource-loading child so refresh does
  not discard it. PR67 already contains the authored current-job/generation
  replay/render readiness and fixed focus metadata. The first presence-page Next
  action now uses the existing passive same-attempt trace, preserving the same
  single keyboard action, target, 100-Tab cap and readiness budget.

  The old separate browser-result shell wrapper is deliberately not carried
  forward. PR67 directly propagates the guarded runner's result and keeps the
  exact protected workflow baseline. The old wrapper only separated outer exit
  statuses 1–127 from 128–255; the latter could be a signal or a high exit code
  and neither category identifies an inner browser or assertion failure. It is
  not claimed equivalent metadata. Its limited extra signal does not justify a
  protected workflow rewrite for the current integration; no historical failure
  is explained by this choice.

PR67 contains later association unlink, fixture-only retained reuse and temporary
review context. The integration preserves their behavior: history is not current
acceptance, plan summaries do not confer source authority, and selected deletion
still uses the existing server endpoint and owner capability. Branch overlap is
not by itself proof of byte-for-byte equivalence or successful merging.

## Verification and remaining work

The first PR68 hosted operator attempt on the original integration head failed
with an unknown-reason `RuntimeError` in the selected-job deletion stage; its
exact action is not established by that receipt. The local follow-up records
only a closed subphase for that existing stage on a future failure. It emits no
DOM text, identifiers or payloads, adds no stage frames, and does not change the
keyboard action, assertion, deadline or failure. This is diagnostic evidence,
not a product or runtime repair. Preserve the failed receipt separately.

The next hosted attempt reported an `AssertionError` while confirming deletion;
the available category does not distinguish focus readiness from waiting for the
dialog to close. A further fixed split records those actions without changing
the focus operation, Enter keypress or close assertion. No cause is established.

Two subsequent attempts on `ca045bdefb4cf4c54a7d49d4b2d55dbbe201a465` reported
an unknown-reason `RuntimeError` at `open_job` and `open_confirmation`,
respectively. Those labels cannot identify the failing operation. The local
diagnostic candidate separates focus and Enter, then the three existing dialog
content assertions, for the cancel and confirm attempts. On failure of the
first content assertion only, a bounded observation reports whether an open
dialog has a nonzero box; it emits no text, identifiers, request data or
exception message. The observation is not proof of visibility or causality.
The same keyboard sequence, assertion budgets, original errors and protected
runner remain in force. Hosted verification of this diagnostic is pending; it
is not a claimed fix for either failure.

The first hosted run of that diagnostic reported an unknown-reason runtime
failure during receipt checks. Closing the dialog does not establish a successful
write: the UI closes it after both success and failure. A further local-only
candidate separates the three existing receipt assertions and, only on their
failure, classifies a fixed UI state such as verified/fenced, verified/other,
submitted/unverified or awaiting submission. No receipt contents, identifiers
or error text are emitted. This snapshot is an observation after failure, not a
server receipt or an explanation of the historical failure.
The previously published dialog snapshot was attempted after leaving the
Playwright context, when the page could already be unavailable. The local
candidate captures the same bounded observation inside the failing assertion's
context and always rethrows the original failure; receipt snapshots follow the
same rule. This corrects diagnostic timing only, not the deletion workflow.

The next local diagnostic observes exceptions inside the Playwright context,
before its teardown can obscure the triggering operation. It exports only a
fixed exception/cause category, an owned source-function category and line,
bounded browser/page/receiver flags and admission count, and whether context
cleanup replaced the original exception. It preserves both the original action
and existing exception propagation. Coordinates are meaningful only against
the exact tested source. A missing snapshot or a category alone cannot prove a
root cause; no browser messages, URLs, tenant identifiers or payloads are
included. This candidate has not been run in the protected hosted browser.
The installed journey has its own browser entrypoint: its local correction
installs the same capture inside both its Playwright and observer contexts, so
capture exits before either owner. Source coordinates accept only the two
known image paths and the corresponding local checkout files, including the
explicit `operator_ui_helpers.py` image alias. A shared basename in an unrelated
path is not accepted. This adds evidence only; it does not establish why a
previous sandbox or deletion operation failed.

That hosted application's backend completed 7,372 assigned cases with one
failure in the fixed-phase source contract: the original test scanned only
`main`, while the diagnostic moved markers into two helpers. The local candidate
checks the explicit helper markers as well as the retained legacy value; it
does not weaken the phase allowlist. The narrow diagnostic development command
is `bash scripts/check_operator_diagnostics.sh`, which includes that source
contract alongside the focus and protocol tests. It is not a substitute for
the full partition, actual database/browser execution or the required join.

The same hosted head separately failed parser memory verification after eleven
daemon observations reported exit 137 without `OOMKilled`; this does not prove
why the process exited or satisfy the existing OOM gate. Installed XML reported
one failed authored-PDF case out of six, waiting for a CSV export, alongside a
publisher nonzero-exit observation. Those facts do not establish their causal
relationship or repair either failure.

That attempt also failed an installed XML case with the existing redirect-order
refusal after callback delivery. Its generic category did not identify the
rejecting check. Fixed rejection-location categories distinguish the original
fail-closed checks without changing their predicates, exception, or login budget;
they do not contain authentication values. This failure remains unexplained.

On the following head the parser workflow failed during its mandatory memory
enforcement stage; the stage alone does not establish the failed operation or
daemon state. A fixed-category receipt distinguishes the existing operation,
observed memory state and owned cleanup, without changing the isolation limits,
OOM assertions or error handling. The failure remains unexplained.

On the same head, the keyboard journey failed earlier during contact suppression,
before deletion was reached. Fixed subphases identify the existing action without
reporting contact values. An installed XML journey separately reached the existing
failed-navigation ordering refusal; fixed categories now distinguish its original
latched, inactive, unarmed and duplicate conditions. These are diagnostic labels:
the original refusal, keyboard sequence, cleanup and budgets remain unchanged.
Neither observation establishes a root cause or repairs earlier failures.

The existing component tests are carried forward with added checks for unlink,
malformed history, unpersisted plans and simultaneous workspace lifetimes. The
older synthetic keyboard flows for saved draft, recorded history and selected
job deletion are authored together against the current guest; the last observed
keyboard run stopped before deletion. Eleven selected PostgreSQL cases passed on
the initial PR68 source with owned disposable resources and verified cleanup;
later exact-head capacity SQL runs also passed. Local collection or skips alone
do not establish SQL execution. The SQL cases are assigned once to the existing
capacity SQL partition. The previous accepted capacity run used 743 of its existing 1,200
work seconds; that margin is observed, not a guarantee for the expanded set.
The exact-inventory and same-tree zero-skip join remain required.

Before publication or product acceptance: inspect the complete source diff;
execute the actual scoped SQL and keyboard cases with authorized fixture
resources; run all normal exact-head hosted workflows and the matching-tree join;
and review historical timeout/diagnostic failures separately. No prior green Draft transfers its
acceptance to this local candidate. Interactive buyer presentation still needs a
supported isolated human-viewing workflow; the genuine-CI-only guest must not be
converted into a local bypass. Real publisher rights, operational readiness,
security and integration review, UAT and production release remain separate.
