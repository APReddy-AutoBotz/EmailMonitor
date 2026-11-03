import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { JobDeletion, confirmJobDeletion, deletionJob, deletionReceipt } from './jobDeletion'
import type { Job } from './models'
import type { Context, Resource } from './ui'
const org = '00000000-0000-4000-8000-000000000001', id = '00000000-0000-4000-8000-000000000002'
const job: Job = { id, kind: 'extraction', state: 'completed', row_version: 4, generation: 2, created_at: '2026-01-01T00:00:00Z', discovery_complete: true }
const receipt = { organization_id: org, job_id: id, id: '00000000-0000-4000-8000-000000000003', reason: 'owner_request', stage: 'fenced', created_at: '2026-01-01T01:00:00Z', purged_at: null, backup_replay_required: true }
function setup() {
  const scope = new ApiScope(org, 'synthetic-only'), confirm = vi.fn(), attempted = vi.fn(), received = vi.fn()
  const read = vi.spyOn(scope, 'request').mockResolvedValue(job), write = vi.spyOn(scope, 'write').mockResolvedValue(receipt)
  const context: Context = { scope, can: cap => cap === 'organization.lifecycle', confirm, act: vi.fn(), refresh: vi.fn(), identity: 'synthetic-only', zone: 'UTC', revision: 0, openJob: vi.fn() }
  const resource: Resource<Job> = { data: job, loading: false }
  const prepare = (reason = 'owner_request') => confirmJobDeletion(context, resource, id, reason, attempted, received)
  const commit = () => (confirm.mock.calls[0][2] as () => Promise<void>)()
  return { scope, context, resource, confirm, attempted, received, read, write, prepare, commit }
}
describe('selected job deletion staging', () => {
  it('requires explicit reason and confirmation; cancellation sends nothing', () => {
    const s = setup(); expect(() => s.prepare('retention_expired')).toThrow('explicit'); s.prepare()
    expect(s.confirm.mock.calls[0][1]).toContain(id)
    expect(s.confirm.mock.calls[0][1]).toContain('all existing exports in this organization')
    expect(s.confirm.mock.calls[0][1]).toContain('Physical purge')
    expect(s.read).not.toHaveBeenCalled(); expect(s.write).not.toHaveBeenCalled()
  })
  it.each(['owner_request', 'privacy_request'])('rereads exact job and stages only selected job: %s', async reason => {
    const s = setup(); s.prepare(reason); await s.commit()
    expect(s.read).toHaveBeenCalledExactlyOnceWith('/jobs/' + id)
    expect(s.write).toHaveBeenCalledExactlyOnceWith('/privacy/deletions', { job_id: id, reason })
    expect(s.attempted).toHaveBeenCalledOnce(); expect(s.received).toHaveBeenCalledWith(receipt)
    await expect(s.commit()).rejects.toThrow('already'); expect(s.write).toHaveBeenCalledOnce()
  })
  it.each(['association.review', 'source.policy.manage', 'membership.manage'])('does not borrow %s authority', cap => {
    const s = setup(); s.context.can = value => value === cap
    expect(() => s.prepare()).toThrow('owner'); expect(s.confirm).not.toHaveBeenCalled()
    expect(renderToStaticMarkup(<JobDeletion context={s.context} resource={s.resource} id={id} />)).toBe('')
  })
  it.each([{ loading: true, data: job }, { loading: false, stale: true, data: job }, { loading: false, error: 'refused', data: job }, { loading: false }])('refuses incomplete/stale data', resource => {
    const s = setup(); expect(deletionJob(s.context, resource, id)).toBeUndefined()
  })
  it.each([{ id: org }, { kind: 'other' }, { state: 'running' }, { row_version: 5 }, { generation: 3 }])('rejects changed job before write', async patch => {
    const s = setup(); s.prepare(); s.read.mockResolvedValue({ ...job, ...patch })
    await expect(s.commit()).rejects.toThrow('changed'); expect(s.write).not.toHaveBeenCalled()
  })
  it('does not accept a closed scope or revoked capability', async () => {
    const s = setup(); s.prepare(); s.context.can = () => false
    await expect(s.commit()).rejects.toThrow('owner'); expect(s.write).not.toHaveBeenCalled()
    s.scope.close(); expect(deletionJob(s.context, s.resource, id)).toBeUndefined()
  })
  it.each([{ job_id: null }, { job_id: org }, { organization_id: id }, { id: 'bad' }, { stage: 'complete' }, { backup_replay_required: false }, { created_at: 'bad' }, { purged_at: '2026-01-01' }])('refuses malformed or broadened receipts', async patch => {
    const s = setup(); s.prepare(); s.write.mockResolvedValue({ ...receipt, ...patch })
    await expect(s.commit()).rejects.toThrow('could not be verified'); expect(s.received).not.toHaveBeenCalled()
    await expect(s.commit()).rejects.toThrow('already'); expect(s.write).toHaveBeenCalledOnce()
  })
  it('preserves server refusal and suppresses late receipts on scope closure', async () => {
    const s = setup(); s.prepare(); s.write.mockRejectedValue(new Error('server refusal'))
    await expect(s.commit()).rejects.toThrow('server refusal'); expect(s.received).not.toHaveBeenCalled()
    const late = setup(); late.prepare(); late.write.mockImplementation(async () => { late.scope.close(); return receipt })
    await expect(late.commit()).rejects.toThrow('could not be verified'); expect(late.received).not.toHaveBeenCalled()
  })
  it('accepts an existing server receipt without relabeling its reason or purge state', () => {
    const prior = { ...receipt, reason: 'privacy_request', stage: 'purged', purged_at: '2026-01-01T02:00:00Z' }
    expect(deletionReceipt(prior, org, id)).toEqual(prior)
    expect(deletionReceipt({ ...prior, purged_at: null }, org, id)).toBeUndefined()
  })
  it('shows staged, not physical-purge, semantics and initially disables submission', () => {
    const s = setup(); const html = renderToStaticMarkup(<JobDeletion context={s.context} resource={s.resource} id={id} />)
    expect(html).toContain('does not perform physical purge or erase backups')
    expect(html).toContain('disabled=""'); expect(html).not.toContain('Purge now')
  })
})
