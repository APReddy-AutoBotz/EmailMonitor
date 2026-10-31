import { useMemo, useState } from 'react'
import { ApiError, errorMessage } from './client'
import type { Job } from './models'
import { Time, uid, type Context, type Resource } from './ui'

type Reason = 'privacy_request' | 'owner_request'
export type DeletionReceipt = { organization_id: string; id: string; job_id: string; reason: Reason | 'retention_expired'; stage: 'fenced' | 'purged'; created_at: string; purged_at: string | null; backup_replay_required: true }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export function deletionJob(context: Context, resource: Resource<Job>, id: string): Job | undefined {
  const job = resource.data
  return context.scope.closed || !context.can('organization.lifecycle') || !uuid.test(id) || resource.loading || resource.stale || resource.error || !job || job.id !== id || job.kind !== 'extraction' ? undefined : job
}
export function deletionReceipt(value: unknown, organization: string, job: string): DeletionReceipt | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const row = value as DeletionReceipt
  if (row.organization_id !== organization || row.job_id !== job || typeof row.id !== 'string' || !uuid.test(row.id) || !['privacy_request', 'owner_request', 'retention_expired'].includes(row.reason) || !['fenced', 'purged'].includes(row.stage) || row.backup_replay_required !== true || typeof row.created_at !== 'string' || !Number.isFinite(Date.parse(row.created_at)) || (row.stage === 'fenced' ? row.purged_at !== null : typeof row.purged_at !== 'string' || !Number.isFinite(Date.parse(row.purged_at)))) return undefined
  return row
}
export function confirmJobDeletion(context: Context, resource: Resource<Job>, id: string, reason: string, attempted: () => void, received: (receipt: DeletionReceipt) => void) {
  const job = deletionJob(context, resource, id)
  if (!job) throw new ApiError(409, 'Refresh the selected job and current owner permission before staging deletion.')
  if (!['privacy_request', 'owner_request'].includes(reason)) throw new ApiError(422, 'Choose an explicit deletion reason.')
  const captured = { ...job }, organization = context.scope.organization, selectedReason = reason as Reason
  let submitted = false
  context.confirm('Stage job deletion', `Stage deletion for job ${id} only. Reason: ${selectedReason.replaceAll('_', ' ')}. The server fences its work and retained data immediately and invalidates all existing exports in this organization, including exports from other jobs. This is not cancellation or an undoable review action. Physical purge and backup tombstone replay are separate operations; this screen does not perform them.`, async () => {
    if (submitted) throw new ApiError(409, 'This confirmation has already submitted a request. Verify its outcome before retrying.')
    if (context.scope.closed || !context.can('organization.lifecycle')) throw new ApiError(403, 'Current owner permission is unavailable.')
    const current = await context.scope.request<Job>('/jobs/' + uid(id))
    if (context.scope.closed || context.scope.organization !== organization || !context.can('organization.lifecycle') || !current || current.id !== id || current.kind !== captured.kind || current.row_version !== captured.row_version || current.generation !== captured.generation || current.state !== captured.state) throw new ApiError(409, 'The selected job changed. Refresh and confirm again.')
    if (submitted) throw new ApiError(409, 'This confirmation has already submitted a request.')
    submitted = true; attempted()
    const value = await context.scope.write<unknown>('/privacy/deletions', { job_id: id, reason: selectedReason })
    const receipt = deletionReceipt(value, organization, id)
    if (context.scope.closed || !receipt) throw new ApiError(0, 'Deletion outcome could not be verified. Do not resubmit without checking current state.')
    received(receipt)
  })
}
export function JobDeletion({ context, resource, id }: { context: Context; resource: Resource<Job>; id: string }) {
  const owner = useMemo(() => ({}), [context.scope, id])
  const [selection, setSelection] = useState<{ owner: object; reason: string }>(), [failure, setFailure] = useState<{ owner: object; error: string }>(), [submission, setSubmission] = useState<{ owner: object; receipt?: DeletionReceipt }>()
  const reason = selection?.owner === owner ? selection.reason : '', error = failure?.owner === owner ? failure.error : undefined, attempted = submission?.owner === owner, receipt = attempted ? submission.receipt : undefined
  if (!context.can('organization.lifecycle') || context.scope.closed) return null
  const current = deletionJob(context, resource, id)
  return <section aria-label="Job deletion"><h4>Stage deletion of this job</h4>
    <p>Owner-only staging immediately fences this job and invalidates all existing exports in this organization. Physical purge and backup tombstone replay remain separate; this screen does not perform physical purge or erase backups.</p>
    {receipt ? <div role="status"><p>Verified deletion receipt: {receipt.id}. Job {receipt.job_id} is {receipt.stage}. Reason: {receipt.reason.replaceAll('_', ' ')}.</p><p>Recorded <Time value={receipt.created_at} zone={context.zone} />. Backup tombstone replay remains required. No physical purge was requested by this screen.</p></div> : attempted ? <p role="status">A deletion request was submitted. Its outcome is unverified here; do not automatically retry. Verify current state using the supported lifecycle runbook.</p> : <>
      {!current && <p role="status">A current readable extraction job is required.</p>}
      <label>Deletion reason<select value={reason} onChange={event => { setSelection({ owner, reason: event.target.value }); setFailure(undefined) }}><option value="">Choose a reason</option><option value="privacy_request">Privacy request</option><option value="owner_request">Owner request</option></select></label>
      <button disabled={!current || !reason} onClick={() => { try { confirmJobDeletion(context, resource, id, reason, () => setSubmission({ owner }), receipt => setSubmission({ owner, receipt })) } catch (failure) { setFailure({ owner, error: errorMessage(failure) }) } }}>Review job deletion</button>
    </>}{error && <p role="alert">{error}</p>}
  </section>
}
