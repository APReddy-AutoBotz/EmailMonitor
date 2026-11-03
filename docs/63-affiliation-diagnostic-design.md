# Bounded affiliation diagnostic design (unpublished candidate)

## Evidence and boundary

Six authored synthetic counterfactuals reproduce a conservative parser behavior:
with two authors, two reserved-domain email candidates and one unlabelled direct
textfn affiliation, no author references yields two affiliations. One valid
correspondence-only reference on the first author suppresses implicit affiliation
for both authors, preserving two authors/two candidates and partial status with
unsupported_affiliation. A footnote-only reference has the same effect. Labels
also suppress implicit selection. Explicit affiliation references restore
selection; an explicitly selected affiliation missing textfn remains partial.
The initial fixture attempt omitted required correspondence text and correctly
returned unsupported_structure; the fixture was corrected before assertions passed.

This proves the synthetic counterfactual, not the cause of the previously recorded
real-sample partial result. No real sample is acquired, re-parsed or copied here.
The PR42 one-shot workflow and runner remain byte-for-byte unchanged.

## Proposed implementation boundary

Add a separate fixed diagnostic entry and closed result schema. Leave normal
parse_article, XML observations, identity/association rules and tenant/API/queue
paths unchanged. The diagnostic reuses the bounded inert XML tree and identifier
binding inside an explicitly selected network-none private worker. It receives
the existing canonical capped byte envelope, never an arbitrary command or URL.
It reports only bounded aggregate counters, never node names, values, locators,
identifiers, content digests, excerpts, contacts or arbitrary exception strings.

Counters: group_count, author_count, affiliation_count,
affiliations_with_direct_textfn, labelled_affiliation_count,
author_affiliation_reference_count, author_correspondence_reference_count,
author_footnote_reference_count, authors_without_selected_affiliation,
groups_implicit_disabled_by_reference, groups_implicit_disabled_by_label,
selected_affiliations_missing_textfn. All counters are strict integers in 0..20000;
refuse rather than silently saturate. Counters describe structure/selection,
not accuracy or accepted identity. References are validated through the existing
resolver; duplicate/missing/multi-ID references refuse with a fixed category.
Unsupported or malformed inputs return no partial counters.

Use a separate diagnostic command and environment marker, explicit host profile
verification and a closed versioned diagnostic envelope; ordinary/private parsing
must reject diagnostic envelopes and vice versa. All existing limits remain:
network none, non-root, capabilities dropped, no-new-privileges, seccomp, read-only,
no host mounts, memory/CPU/PID/FD/core limits and bounded stdin/stdout/deadlines.
Host admission must preserve independently supplied rights/provenance decisions,
regular-file/no-symlink checks and trusted private composition. No CLI accepting
real paths, acquisition workflow, source authorization or workflow trigger is added.
The current one-shot rights decision must not be treated as approval for another run.

## Verification before any publication

Independently review this design and synthetic evidence. Then implement a narrow
pure diagnostic core and explicit isolated transport/admission composition.
Test strict decoding, wrong/mixed marker/command/profile refusal, cross-mode
rejection, no sensitive output, malformed/unsupported XML, reference ambiguity,
all parser bounds, unchanged normal observations and unchanged one-shot files.
Actual isolated checks must use authored synthetic bytes only. Report local
mock/pure checks separately from actual Docker tests and whole-repository checks.
No migration or production configuration is required. No merge/deploy/live access.

## Independent design review resolutions

- First run parse_article and XmlExpectation.check_observation inside the guest;
  unsupported observations refuse. This preserves complete author/correspondence,
  evidence/observation and profile/digest/identifier limits before counting. A
  second bounded inert tree traversal computes counters only; both stay isolated.
- group_count counts direct head author groups; author_count counts direct author
  and collaboration nodes; affiliation_count counts direct group affiliations;
  affiliations_with_direct_textfn counts affiliations with at least one direct textfn;
  labelled_affiliation_count counts affiliations having a direct label.
- Reference counters count validated author reference edges by target category.
  authors_without_selected_affiliation counts authors with zero selected nodes,
  even if affiliation nodes exist; it does not count empty emitted strings.
  selected_affiliations_missing_textfn counts selected author-to-affiliation edges
  without direct textfn, not unique affiliation nodes.
- Disabled counters count groups where references or labels respectively make
  that implicit predicate false; both may count the same group.
- New admission purpose and rights scope: one-file-private-affiliation-diagnostic.
  The existing one-shot RightsDecision/purpose is not an accepted authorization.
- Input deliberately reuses xml-input-v1. Cross-mode rejection applies to output
  envelopes and guest command/marker selection; it is not a new request protocol.
  New host verifies its exact command/profile/marker without rewriting metadata.
- Tests also cover one-author-only affiliation edges, multiple groups, simultaneous
  reference/label suppression and unchanged candidate review/position semantics.
