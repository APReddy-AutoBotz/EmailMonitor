import { useState } from 'react'
import { ApiError, errorMessage } from './client'
import type { Contact } from './models'
import { uid, type Context, type Resource } from './ui'

type Reason = 'privacy_request' | 'source_restriction'
export function suppressionContact(context: Context, resource: Resource<Contact>, selected: Contact): Contact | undefined {
  const row = resource.data
  return context.scope.closed || !context.can('source.policy.manage') || resource.loading || resource.error || resource.stale || !row || row.organization_id !== context.scope.organization || row.batch_id !== selected.batch_id || row.association_id !== selected.association_id ? undefined : row
}
export function confirmContactSuppression(context: Context, resource: Resource<Contact>, selected: Contact, reason: string, closeEvidence: () => void) {
  const row = suppressionContact(context, resource, selected)
  if (!row) throw new ApiError(409, 'Refresh the current contact and permissions before suppression.')
  if (!['privacy_request', 'source_restriction'].includes(reason)) throw new ApiError(422, 'Choose an explicit suppression reason.')
  const captured = { ...row }, selectedReason = reason as Reason
  closeEvidence()
  context.confirm('Suppress observed contact', `Suppress the retained address ${captured.raw_address} throughout this organization, including matching records across jobs. Reason: ${selectedReason.replaceAll('_', ' ')}. Existing matching data and exports may become unavailable. This is not limited to the selected association and is not an undoable review rejection.`, async () => {
    if (context.scope.closed || !context.can('source.policy.manage')) throw new ApiError(403, 'Current suppression permission is unavailable.')
    const current = await context.scope.request<Contact>('/contacts/' + uid(captured.association_id) + '?batch_id=' + uid(captured.batch_id))
    if (context.scope.closed || !context.can('source.policy.manage') || !current || current.organization_id !== context.scope.organization || current.batch_id !== captured.batch_id || current.association_id !== captured.association_id || current.revision !== captured.revision || current.raw_address !== captured.raw_address) throw new ApiError(409, 'The selected contact changed. Refresh and confirm again.')
    // Send the retained value unchanged; only the existing server privacy grammar normalizes it.
    const receipt = await context.scope.write<{ organization_id: string; id: string; kind: string; active: boolean }>('/privacy/suppressions', { kind: 'contact', value: captured.raw_address, reason: selectedReason })
    if (context.scope.closed || !receipt || receipt.organization_id !== context.scope.organization || receipt.kind !== 'contact' || receipt.active !== true || typeof receipt.id !== 'string') throw new ApiError(0, 'Suppression outcome could not be verified. Refresh current data before any retry.')
  })
}
export function ContactSuppression({ context, resource, selected, closeEvidence }: { context: Context; resource: Resource<Contact>; selected: Contact; closeEvidence: () => void }) {
  const [reason, setReason] = useState(''), [error, setError] = useState<string>()
  const current = suppressionContact(context, resource, selected)
  return <section aria-label="Contact suppression"><h4>Contact suppression</h4>
    {!context.can('source.policy.manage') ? <p>Suppression requires the existing source-policy management capability. Review permission alone does not allow it.</p> : <>
      <p>Use only for an explicit privacy request or source restriction. Matching-address suppression applies throughout this organization, across jobs; withdrawal does not restore previously fenced records.</p>
      {!current && <p role="status">A current readable contact is required before suppression.</p>}
      <label>Suppression reason<select value={reason} onChange={event => { setReason(event.target.value); setError(undefined) }}><option value="">Choose a reason</option><option value="privacy_request">Privacy request</option><option value="source_restriction">Source restriction</option></select></label>
      <button type="button" disabled={!current || !reason} onClick={() => { try { confirmContactSuppression(context, resource, selected, reason, closeEvidence) } catch (failure) { setError(errorMessage(failure)) } }}>Review contact suppression</button>
      {error && <p role="alert">{error}</p>}
    </>}
  </section>
}
