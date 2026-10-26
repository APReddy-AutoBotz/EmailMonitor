import type { ApiScope } from './client'
import type { Contact } from './models'
import { Time, uid, useResource, type Resource } from './ui'

export type ReviewRecord = { id: string; association_id: string; actor: string; action: 'accept' | 'reject' | 'correct'; expected_revision: number; reason: string; created_at: string }
export function currentHistoryContact(resource: Resource<Contact>, organization: string, batch: string, association: string): boolean {
  return !resource.loading && !resource.error && !resource.stale && resource.data?.organization_id === organization && resource.data.batch_id === batch && resource.data.association_id === association
}
export function ReviewHistoryPanel({ resource, current, association, zone }: { resource: Resource<ReviewRecord[]>; current: boolean; association: string; zone: string }) {
  const unavailable = !current || resource.loading || resource.error || resource.stale || !Array.isArray(resource.data) || resource.data.length > 100
  const rows = unavailable ? [] : resource.data!.filter(row => row.association_id === association)
  return <section aria-label="Recorded review history"><h4>Recorded review history</h4>
    {unavailable ? <p role="status">{current && resource.loading ? 'Loading current review history…' : 'Current review history is unavailable. Refresh before relying on earlier decisions.'}</p> : <>
      <p>Only recorded decisions for this association are shown, in server order. The batch response is limited to its earliest 100 records; this is not a complete audit export.</p>
      {resource.data!.length === 100 && <p role="status">Batch history limit reached. Later decisions may be absent, including decisions for this association.</p>}
      {rows.length === 0 ? <p>No decisions for this association in the loaded batch window. This does not establish that it was never reviewed.</p> : <details><summary>Inspect recorded review decisions ({rows.length})</summary><ol>{rows.map(row => <li key={row.id}>
        <p>Recorded action: {row.action} · Expected association revision: {row.expected_revision}</p>
        <p>Actor ID: {row.actor} · <Time value={row.created_at} zone={zone} /></p><blockquote>{row.reason}</blockquote>
      </li>)}</ol></details>}
      <p>Historical decisions do not establish current acceptance or authority and do not rewrite article evidence.</p>
    </>}
  </section>
}
export function CurrentReviewHistory({ scope, batch, association, contact, zone }: { scope: ApiScope; batch: string; association: string; contact: Resource<Contact>; zone: string }) {
  const current = !scope.closed && currentHistoryContact(contact, scope.organization, batch, association)
  const resource = useResource<ReviewRecord[]>(scope, current ? '/association-batches/' + uid(batch) + '/reviews' : null)
  return <ReviewHistoryPanel resource={resource} current={current} association={association} zone={zone} />
}
