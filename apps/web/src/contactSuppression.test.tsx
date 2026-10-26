import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { ContactSuppression, confirmContactSuppression, suppressionContact } from './contactSuppression'
import type { Contact } from './models'
import type { Context, Resource } from './ui'
const org = '00000000-0000-4000-8000-000000000001'
const row = { organization_id: org, association_id: '00000000-0000-4000-8000-000000000002', batch_id: '00000000-0000-4000-8000-000000000003', revision: 2, raw_address: 'Authored.Contact@example.org' } as Contact
function setup(allowed = true) {
  const scope = new ApiScope(org, 'synthetic-only')
  const read = vi.spyOn(scope, 'request').mockResolvedValue(row)
  const write = vi.spyOn(scope, 'write').mockResolvedValue({ organization_id: org, id: 'owned-synthetic-receipt', kind: 'contact', active: true })
  const confirm = vi.fn(), close = vi.fn()
  const context: Context = { scope, can: capability => allowed && capability === 'source.policy.manage', confirm, act: vi.fn(), refresh: vi.fn(), identity: 'synthetic-only', zone: 'UTC', revision: 0, openJob: vi.fn() }
  const resource: Resource<Contact> = { data: row, loading: false }
  const prepare = (reason = 'privacy_request') => confirmContactSuppression(context, resource, row, reason, close)
  const commit = () => (confirm.mock.calls[0][2] as () => Promise<void>)()
  return { context, scope, read, write, confirm, close, resource, prepare, commit }
}
describe('contextual contact suppression under existing authority', () => {
  it('requires an explicit reason and confirmation; cancel does not read or write', () => {
    const s = setup(); expect(() => s.prepare('')).toThrow('Choose an explicit')
    expect(s.confirm).not.toHaveBeenCalled(); s.prepare()
    expect(s.close).toHaveBeenCalledOnce(); expect(s.confirm).toHaveBeenCalledOnce()
    expect(s.confirm.mock.calls[0][1]).toContain('throughout this organization')
    expect(s.confirm.mock.calls[0][1]).toContain(row.raw_address)
    expect(s.read).not.toHaveBeenCalled(); expect(s.write).not.toHaveBeenCalled()
  })
  it.each(['privacy_request', 'source_restriction'])('rechecks current contact then sends only exact retained address and selected reason', async reason => {
    const s = setup(); s.prepare(reason); await s.commit()
    expect(s.read).toHaveBeenCalledExactlyOnceWith('/contacts/' + row.association_id + '?batch_id=' + row.batch_id)
    expect(s.write).toHaveBeenCalledExactlyOnceWith('/privacy/suppressions', { kind: 'contact', value: row.raw_address, reason })
  })
  it('does not equate review permission with suppression authority', () => {
    const s = setup(false); s.context.can = capability => capability === 'association.review'
    expect(() => s.prepare()).toThrow('Refresh'); expect(s.confirm).not.toHaveBeenCalled()
    const html = renderToStaticMarkup(<ContactSuppression context={s.context} resource={s.resource} selected={row} closeEvidence={s.close} />)
    expect(html).not.toContain('<button'); expect(html).toContain('Review permission alone')
  })
  it.each([{ loading: true, data: row }, { loading: false, stale: true, data: row }, { loading: false, error: 'refused', data: row }, { loading: false }])('refuses unavailable current rows', resource => {
    const s = setup(); expect(suppressionContact(s.context, resource, row)).toBeUndefined()
  })
  it.each([{ organization_id: 'another-org' }, { batch_id: 'another-batch' }, { association_id: 'another-association' }, { revision: 3 }, { raw_address: 'another@example.org' }])('refuses changed confirmation target before writing', async patch => {
    const s = setup(); s.prepare(); s.read.mockResolvedValue({ ...row, ...patch })
    await expect(s.commit()).rejects.toThrow('changed'); expect(s.write).not.toHaveBeenCalled()
  })
  it('refuses an organization/session change after confirmation without a request', async () => {
    const s = setup(); s.prepare(); s.scope.close()
    await expect(s.commit()).rejects.toThrow('permission'); expect(s.read).not.toHaveBeenCalled(); expect(s.write).not.toHaveBeenCalled()
  })
  it('does not write when closure happens during the current-contact read', async () => {
    const s = setup(); s.prepare(); s.read.mockImplementation(async () => { s.scope.close(); return row })
    await expect(s.commit()).rejects.toThrow('changed'); expect(s.write).not.toHaveBeenCalled()
  })
  it('preserves read refusal and write refusal without retries or success', async () => {
    const s = setup(); s.prepare(); s.read.mockRejectedValue(new Error('authored read refusal'))
    await expect(s.commit()).rejects.toThrow('read refusal'); expect(s.write).not.toHaveBeenCalled()
    s.read.mockResolvedValue(row); s.write.mockRejectedValue(new Error('authored write refusal'))
    await expect(s.commit()).rejects.toThrow('write refusal'); expect(s.write).toHaveBeenCalledOnce()
  })
  it('reports an uncertain receipt without retrying or claiming successful suppression', async () => {
    const s = setup(); s.prepare(); s.write.mockResolvedValue({ organization_id: 'other', active: true })
    await expect(s.commit()).rejects.toThrow('could not be verified'); expect(s.write).toHaveBeenCalledOnce()
  })
  it('initially disables submission until the user selects a reason', () => {
    const s = setup(); const html = renderToStaticMarkup(<ContactSuppression context={s.context} resource={s.resource} selected={row} closeEvidence={s.close} />)
    expect(html).toContain('Choose a reason'); expect(html).toContain('disabled=""'); expect(html).toContain('withdrawal does not restore')
  })
})
