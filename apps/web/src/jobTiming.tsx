import type { ApiScope } from './client'
import type { Progress } from './models'
import { Time, uid, useResource, type Resource } from './ui'

export type JobTiming = {
  view_version: 'job-timing-v1'; organization_id: string; job_id: string
  revision: number; generation: number; state: string
  basis: 'first_queued_to_current_terminal_event'
  availability: 'recorded' | 'not_started' | 'not_terminal' | 'not_recorded' | 'inconsistent'
  queued_at: string | null; terminal_at: string | null; elapsed_seconds: number | null
  includes_waiting_and_pauses: true
}
export function JobTimingPanel({ resource, organization, job, progress, zone }: {
  resource: Resource<JobTiming>; organization: string; job: string; progress: Resource<Progress>; zone: string
}) {
  const value = resource.data, current = progress.data
  const unavailable = resource.loading || resource.stale || resource.error || !value || progress.loading || progress.stale || progress.error || !current ||
    value.organization_id !== organization || value.job_id !== job || current.organization_id !== organization || current.job_id !== job ||
    value.revision !== current.revision || value.generation !== current.generation || value.state !== current.state ||
    value.view_version !== 'job-timing-v1' || value.basis !== 'first_queued_to_current_terminal_event' || value.includes_waiting_and_pauses !== true
  const recorded = !unavailable && value.availability === 'recorded' && value.queued_at && value.terminal_at && value.elapsed_seconds !== null && Number.isFinite(value.elapsed_seconds) && value.elapsed_seconds >= 0
  return <section aria-label="Recorded job elapsed time"><h4>Recorded job elapsed time</h4>
    {unavailable ? <p role="status">Current job timing is unavailable. Refresh before relying on earlier values.</p> : recorded ? <dl>
      <div><dt>First queued</dt><dd><Time value={value.queued_at!} zone={zone} /></dd></div>
      <div><dt>Current terminal event</dt><dd><Time value={value.terminal_at!} zone={zone} /></dd></div>
      <div><dt>Queue-to-terminal elapsed seconds</dt><dd>{value.elapsed_seconds!.toFixed(3)}</dd></div>
    </dl> : <p>{value.availability === 'not_terminal' ? 'Not terminal yet; no completed interval is reported.' : value.availability === 'not_started' ? 'No started execution interval is reported.' : 'A complete, consistent retained interval is not recorded; elapsed time is unknown.'}</p>}
    <p>This interval includes waiting and pauses. It is not worker CPU time, review effort, billable usage or a performance guarantee. Continuation jobs have their own intervals.</p>
  </section>
}
export function CurrentJobTiming({ scope, job, progress, revision, zone }: {
  scope: ApiScope; job: string; progress: Resource<Progress>; revision: number; zone: string
}) {
  const resource = useResource<JobTiming>(scope, progress.data ? '/jobs/' + uid(job) + '/timing' : null, revision)
  return <JobTimingPanel resource={scope.closed ? { loading: false } : resource} organization={scope.organization} job={job} progress={progress} zone={zone} />
}
