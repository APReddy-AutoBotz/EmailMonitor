import { useMemo, useState } from 'react'
import { ApiError } from './client'
import type { Job } from './models'
import { launchableSourcePlan, SourcePlanSummary } from './sourcePlanSummary'
import { uid, type Context, type Resource } from './ui'

export function currentDraft(c: Context, resource: Resource<Job>, id: string): Job | undefined {
  const job = resource.data
  return c.scope.closed || !c.can('source.acquire') || resource.loading || resource.stale || resource.error || !job || job.id !== id || job.kind !== 'extraction' || job.state !== 'draft' ? undefined : job
}
const same = (a: Job, b: Job) => a.id === b.id && a.kind === b.kind && a.state === b.state && a.row_version === b.row_version && a.generation === b.generation
export type SavedPlan = { job: Job; detail: Record<string, unknown>; launch: () => Promise<void> }
export async function planSavedDraft(c: Context, resource: Resource<Job>, id: string): Promise<SavedPlan> {
  const initial = currentDraft(c, resource, id)
  if (!initial) throw new ApiError(409, 'A current readable draft and source acquisition permission are required.')
  const captured = { ...initial }, scope = c.scope
  const authorized = () => !scope.closed && c.can('source.acquire')
  const path = '/jobs/' + uid(id)
  const current = await scope.request<Job>(path)
  if (!authorized() || !current || !same(captured, current)) throw new ApiError(409, 'The saved draft changed. Refresh before planning.')
  const detail = await scope.write<Record<string, unknown>>(path + '/plan', { expected_revision: current.row_version })
  if (!authorized()) throw new ApiError(409, 'The planning session is no longer current.')
  const planned = await scope.request<Job>(path)
  const plan = detail?.plan as Record<string, unknown> | undefined
  if (!authorized() || !planned || planned.id !== id || planned.kind !== 'extraction' || planned.state !== 'draft' || planned.generation !== captured.generation || !detail || detail.organization_id !== scope.organization || detail.job_id !== id || detail.generation !== planned.generation || !plan || !launchableSourcePlan(detail)) throw new ApiError(409, 'No current launchable plan for this saved draft. Unsupported input or policy changes require a new extraction request.')
  const snapshot = { ...planned }
  let submitted = false
  return { job: snapshot, detail, launch: async () => {
    if (submitted) throw new ApiError(409, 'Launch was already submitted. Inspect current job state before any further action.')
    if (!authorized()) throw new ApiError(403, 'Current source acquisition permission is unavailable.')
    const latest = await scope.request<Job>(path)
    if (!authorized() || !latest || !same(snapshot, latest)) throw new ApiError(409, 'The planned draft changed. Refresh and validate its plan again.')
    if (submitted) throw new ApiError(409, 'Launch was already submitted.')
    submitted = true
    await scope.write(path + '/start', { expected_revision: latest.row_version })
    if (authorized()) c.openJob(id)
  } }
}
export function SavedDraft({ context: c, resource, id }: { context: Context; resource: Resource<Job>; id: string }) {
  const owner = useMemo(() => ({}), [c.scope, id])
  const [result, setResult] = useState<{ owner: object; plan: SavedPlan }>(), [attempt, setAttempt] = useState<object>()
  if (!c.can('source.acquire') || c.scope.closed || resource.data?.state !== 'draft') return null
  const draft = currentDraft(c, resource, id), plan = result?.owner === owner ? result.plan : undefined
  return <section aria-label="Saved draft plan"><h4>Continue this saved draft</h4><p>Validate this job's original request under current source policy. Review the returned plan before explicitly launching. This does not create a replacement job or change the saved request.</p>
    <button disabled={!draft || attempt === owner} onClick={() => void c.act('Validate saved draft', async () => { setResult(undefined); const next = await planSavedDraft(c, resource, id); if (!c.scope.closed) setResult({ owner, plan: next }) }, 'Saved draft plan validated. Review it before launch.')}>Validate saved draft plan</button>
    {plan && <section aria-label="Validated saved draft"><SourcePlanSummary plan={plan.detail} job={plan.job} /><button disabled={!draft || !same(plan.job, draft) || attempt === owner} onClick={() => void c.act('Launch saved draft', async () => { setAttempt(owner); await plan.launch() }, 'Saved draft launch submitted. Inspect current job state.')}>Launch this saved draft</button></section>}
    {attempt === owner && <p role="status">A launch action was attempted. Refresh and inspect current job state; this screen does not automatically retry an uncertain submission.</p>}
  </section>
}
