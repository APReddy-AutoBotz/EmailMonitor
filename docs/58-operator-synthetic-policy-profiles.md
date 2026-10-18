# Operator synthetic policy profiles

## Bounded EM-003 / EM-012 integration

Sources exposes two closed synthetic proposals through the existing source-policy API. Static HTML remains the default with unchanged permissions and raw retention of 24 hours. Controlled provider XML is an explicit selection with fetch_xml instead of fetch_html and raw retention of zero hours. Both retain excerpts for 30 days and contacts for 90 days. Neither unions permissions with the current policy. Selection alone makes no request; submission creates a pending version, and approval is a separate authorized action.

The form shows proposed operations, retention and a 24-hour expiry from submission. The approval dialog shows the actual pending version, revision, permissions, retention and expiry returned by the server, independently of any newly selected proposal. The existing API immediately makes a proposed replacement the current head; the form warns that this can fence jobs and downloads until separate approval. Historical versions remain immutable.

Only existing owner/data-steward capabilities expose management controls. Server authorization, optimistic version/revision checks, tenant isolation and audit remain authoritative. No schema, migration, dependency, credential, policy default, provider transport or worker protocol changes are introduced.

## Actual acceptance

The controlled provider journey starts with no synthetic policy. The authenticated operator uses the isolated keyboard UI to select XML, submit review, switch the unsubmitted selector back to HTML, inspect and approve the actual pending XML record, then create/plan/start a job. Existing durable outbox, owned publisher, RabbitMQ/registered Celery worker, protected HTTPS acquisition, curated isolated parser, review and CSV/XLSX export remain required. Host assertions verify the browser proposal/approval bodies, SQL policy state/actors and exactly the two policy audit events. Tenant switching must remove management controls and continue to deny exports.

The original static journey verifies the unchanged HTML default. Its eight-second completion wait is unchanged; the separately bounded provider wait and enforced acquisition spacing are unchanged. No isolation, relay, timeout or completion predicate is relaxed.

Nine additional real SQL/API cases exercise XML-shaped authorized/denied roles, replacement semantics, stale approvals, revoked membership and cross-tenant access. Seven frontend cases cover closed profiles, immutable values, summaries and denied management presentation. Local service skips are not actual acceptance.

## Limits and rollback

These profiles authorize only synthetic fixture work. XML still requires the separately composed trusted controlled worker; the default worker refuses provider routes. No real publisher rights, credentials, production runtime or source certification follow from policy approval. Full EM-015/016 source inputs and EM-017 production choices remain outstanding.

Reverting the UI does not erase existing policy history or approval audit. Existing governance actions are required to change a current policy; do not rewrite history or silently restore older permissions. See [validation](../reports/operator-xml-policy-validation.md).

## Direct controlled article input

The subsequent EM-006/012 acceptance uses the same explicit XML policy review for a separate exact synthetic article-URL journey. It requires no search or unrelated article acquisition, one durable article/effect/review and both exports, retaining the original keyword journey and every timeout/isolation bound. [Direct-URL validation](../reports/operator-direct-url-validation.md) distinguishes durable source URL from provider canonical identity and records pending actual gates.

## Subsequent tooltip profile integration

[Runbook59](59-operator-tooltip-browser.md) adds a third closed HTML-plus-browser
synthetic profile with explicit job opt-in and separately composed trusted worker.
The original HTML default, XML proposal and separate current-record approval are
unchanged. Its actual acceptance is tracked separately from this XML milestone.
