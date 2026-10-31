import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Job } from './models'
import { SavedDraft, currentDraft, planSavedDraft } from './savedDraft'
import { SourcePlanSummary } from './sourcePlanSummary'
import type { Context, Resource } from './ui'
const org = '00000000-0000-4000-8000-000000000001', id = '00000000-0000-4000-8000-000000000002'
const job: Job = { id, kind: 'extraction', state: 'draft', row_version: 2, generation: 1, created_at: '2026-01-01T00:00:00Z', discovery_complete: false }
const detail = { organization_id: org, job_id: id, generation: 1, policy_version: 3, plan: { classification: 'article' } }
function setup() {
  const scope = new ApiScope(org, 'synthetic-only'), openJob = vi.fn()
  const read = vi.spyOn(scope, 'request').mockResolvedValue(job), write = vi.spyOn(scope, 'write').mockResolvedValue(detail)
  const context: Context = { scope, can: cap => cap === 'source.acquire', openJob, confirm: vi.fn(), act: vi.fn(), refresh: vi.fn(), identity: 'synthetic-only', zone: 'UTC', revision: 0 }
  const resource: Resource<Job> = { data: job, loading: false }
  return { scope, read, write, context, resource, openJob, plan: () => planSavedDraft(context, resource, id) }
}
describe('saved draft continuation', () => {
  it.each(['article', 'search_results'])('plans the existing %s job and requires a separate launch', async classification => {
    const s = setup(); s.write.mockResolvedValue({ ...detail, plan: { classification } })
    const plan = await s.plan()
    expect(s.write).toHaveBeenCalledExactlyOnceWith('/jobs/' + id + '/plan', { expected_revision: 2 })
    expect(s.openJob).not.toHaveBeenCalled()
    await plan.launch()
    expect(s.write).toHaveBeenLastCalledWith('/jobs/' + id + '/start', { expected_revision: 2 })
    expect(s.openJob).toHaveBeenCalledExactlyOnceWith(id)
    await expect(plan.launch()).rejects.toThrow('already'); expect(s.write).toHaveBeenCalledTimes(2)
  })
  it.each(['association.review', 'organization.lifecycle', 'source.policy.manage'])('does not borrow %s permission', async cap => {
    const s = setup(); s.context.can = value => value === cap
    await expect(s.plan()).rejects.toThrow('permission'); expect(s.write).not.toHaveBeenCalled()
    expect(renderToStaticMarkup(<SavedDraft context={s.context} resource={s.resource} id={id} />)).toBe('')
  })
  it.each([{ loading: true }, { loading: false, stale: true }, { loading: false, error: 'refused' }, { loading: false, data: undefined }])('refuses unavailable current data', patch => {
    const s = setup(); expect(currentDraft(s.context, { ...s.resource, ...patch }, id)).toBeUndefined()
  })
  it.each([{ id: org }, { kind: 'fixture_probe' }, { state: 'queued' }, { row_version: 3 }, { generation: 2 }])('refuses stale planning or launch target', async patch => {
    const s = setup(); s.read.mockResolvedValue({ ...job, ...patch })
    await expect(s.plan()).rejects.toThrow('changed'); expect(s.write).not.toHaveBeenCalled()
    const launch = setup(), plan = await launch.plan(); launch.read.mockResolvedValue({ ...job, ...patch })
    await expect(plan.launch()).rejects.toThrow('changed'); expect(launch.write).toHaveBeenCalledTimes(1)
  })
  it.each([{ organization_id: id }, { job_id: org }, { generation: 2 }, { plan: { classification: 'needs_refinement' } }, { plan: { classification: 'unsupported' } }, { plan: null }, { persisted: false }])('does not launch unbound/unsupported plan', async patch => {
    const s = setup(); s.write.mockResolvedValue({ ...detail, ...patch })
    await expect(s.plan()).rejects.toThrow('launchable'); expect(s.write).toHaveBeenCalledTimes(1)
  })
  it('uses the post-plan revision and rejects lifecycle change during planning', async () => {
    const s = setup(); s.read.mockResolvedValueOnce(job).mockResolvedValue({ ...job, row_version: 3 })
    const plan = await s.plan(); await plan.launch()
    expect(s.write).toHaveBeenLastCalledWith('/jobs/' + id + '/start', { expected_revision: 3 })
    const stale = setup(); stale.read.mockResolvedValueOnce(job).mockResolvedValue({ ...job, generation: 2 })
    await expect(stale.plan()).rejects.toThrow('launchable')
  })
  it('keeps the saved reuse request visible without creating a fresh acquisition job', async () => {
    const s = setup()
    const retained = { ...job, request: { input: { type: 'url', url: 'https://synthetic.publisher.example/article-a.html' }, reuse: { mode: 'verified_retained', fresh_since: '2026-10-01T00:00:00Z' } } }
    s.read.mockResolvedValue(retained)
    s.write.mockResolvedValue({ ...detail, plan: { classification: 'article', reason: 'retained_reuse_authored' } })
    const plan = await planSavedDraft(s.context, { data: retained, loading: false }, id)
    expect(renderToStaticMarkup(<SourcePlanSummary plan={plan.detail} job={plan.job} />)).toContain('verified_retained; fresh since 2026-10-01T00:00:00Z')
    await plan.launch()
    expect(s.write.mock.calls.map(call => call[0])).toEqual(['/jobs/' + id + '/plan', '/jobs/' + id + '/start'])
    expect(s.openJob).toHaveBeenCalledWith(id)
  })
  it('discards late planning result after session closure and refuses revoked launch', async () => {
    const s = setup(); s.write.mockImplementation(async () => { s.scope.close(); return detail })
    await expect(s.plan()).rejects.toThrow('session'); expect(s.read).toHaveBeenCalledTimes(1)
    const revoked = setup(), plan = await revoked.plan(); revoked.context.can = () => false
    await expect(plan.launch()).rejects.toThrow('permission'); expect(revoked.write).toHaveBeenCalledTimes(1)
  })
  it('does not retry unknown launch outcomes or navigate after scope closure', async () => {
    const s = setup(), plan = await s.plan(); s.write.mockRejectedValue(new Error('unknown submission'))
    await expect(plan.launch()).rejects.toThrow('unknown'); await expect(plan.launch()).rejects.toThrow('already')
    expect(s.write).toHaveBeenCalledTimes(2); expect(s.openJob).not.toHaveBeenCalled()
    const late = setup(), next = await late.plan(); late.write.mockImplementation(async () => { late.scope.close(); return {} })
    await next.launch(); expect(late.openJob).not.toHaveBeenCalled()
  })
  it('concurrent launch calls submit only once after their reads', async () => {
    const s = setup(), plan = await s.plan()
    const results = await Promise.allSettled([plan.launch(), plan.launch()])
    expect(results.map(value => value.status).sort()).toEqual(['fulfilled', 'rejected'])
    expect(s.write).toHaveBeenCalledTimes(2)
  })
  it('shows explicit planning before any launch control', () => {
    const s = setup(), html = renderToStaticMarkup(<SavedDraft context={s.context} resource={s.resource} id={id} />)
    expect(html).toContain('Validate saved draft plan'); expect(html).not.toContain('Launch this saved draft')
    expect(html).toContain('does not create a replacement job')
  })
})
