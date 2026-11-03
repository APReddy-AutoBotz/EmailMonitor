# Retained article details from contact results

FR-010/017/023 and NFR-011, EM-009/011/012: an operator can open the selected
contact's retained article details directly from Contacts or Review, without
opening the association-review dialog. The previous contact row always claimed
that publication date was unobserved even when retained metadata existed; the
row now offers an explicit details action instead.

The panel uses the existing current-authorized article-metadata precision read
for the selected batch. It displays the existing retained title, journal, DOI,
raw publication-date text, precision annotations and citations; partial,
conflicting, invalid or unavailable dates are not converted into a day or a
source-side search claim. The view does not change a contact, review, evidence,
policy, filter or export, and adds no endpoint, migration, permission or source.
Only one selected details panel is mounted at a time; no metadata read is started
for every row in the page. Explicit close returns keyboard focus to the current
opener when available. If a focused panel is invalidated while its organization
scope is still active, focus returns to the contact view's stable fallback.

Selection is bound to the active scope, contact page, filter generation and
association revision. Filter/page/revision changes, loading/error/stale page
state, a missing or foreign row, and a closed session hide the panel. The existing
metadata request is aborted on unmount and its organization and batch identity
must match; server-side source, policy, suppression and retention checks remain
authoritative. Malformed metadata is unavailable rather than rendered or treated
as an empty article. There is no client-side publication-date filtering.

The React tests use synthetic responses and controlled component handlers to
exercise ownership, stale/foreign/refused data, date precision, conflicting and
malformed metadata, selection replacement and focus restoration. Focus tests use
controlled synthetic element stubs, not a real browser. Local test
results do not establish installed-browser, live-source, database or release
acceptance. Those checks remain pending for this local candidate.
