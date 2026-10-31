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
  unavailable rather than rendered. The original parser-phase diagnostic and
  process-cleanup test-helper changes are not included and need separate
  disposition; they are not product features or claimed equivalent.
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
  replay/render readiness and fixed focus metadata; the sibling's separate
  browser process-outcome wrapper is not included and needs a separate disposition.

PR67 contains later association unlink, fixture-only retained reuse and temporary
review context. The integration preserves their behavior: history is not current
acceptance, plan summaries do not confer source authority, and selected deletion
still uses the existing server endpoint and owner capability. Branch overlap is
not by itself proof of byte-for-byte equivalence or successful merging.

## Verification and remaining work

The existing component tests are carried forward with added checks for unlink,
malformed history, unpersisted plans and simultaneous workspace lifetimes. The
older synthetic keyboard flows for saved draft, recorded history and selected
job deletion are authored together against the current guest; they have not been
executed in genuine isolated browser CI for this new source. The restored real
PostgreSQL history/retention/authority and selected-job deletion cases require a
future explicitly authorized disposable database; local collection or skips do
not establish SQL execution. They are assigned once to the existing capacity SQL
partition. The previous accepted capacity run used 743 of its existing 1,200
work seconds; that margin is observed, not a guarantee for the expanded set.
The exact-inventory and same-tree zero-skip join remain required.

Before publication or product acceptance: inspect the complete source diff;
execute the actual scoped SQL and keyboard cases with authorized fixture
resources; run all normal exact-head hosted workflows and the matching-tree join;
review historical timeout/diagnostic failures separately; and disposition the
remaining sibling test-only diagnostics. No prior green Draft transfers its
acceptance to this local candidate. Interactive buyer presentation still needs a
supported isolated human-viewing workflow; the genuine-CI-only guest must not be
converted into a local bypass. Real publisher rights, operational readiness,
security and integration review, UAT and production release remain separate.
