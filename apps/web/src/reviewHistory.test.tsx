import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Contact } from './models'
import { currentHistoryContact, ReviewHistoryPanel, type ReviewRecord } from './reviewHistory'
import type { Resource } from './ui'
const row: ReviewRecord = { id: 'review-a', association_id: 'association-a', actor: 'actor-a', action: 'correct', expected_revision: 4, reason: 'Authored correction reason', created_at: '2026-10-25T01:30:00Z' }
const render = (resource: Resource<ReviewRecord[]>, current = true, association = 'association-a', zone = 'UTC') => renderToStaticMarkup(<ReviewHistoryPanel resource={resource} current={current} association={association} zone={zone} />)
describe('bounded current-authorized review history', () => {
  it('shows only this association without merging decisions or inferring present acceptance', () => {
    const html = render({ loading: false, data: [row, { ...row, id: 'review-b', association_id: 'association-b', reason: 'Other association private reason' }] })
    for (const text of ['correct', 'revision: 4', 'actor-a', 'Authored correction reason', 'UTC', 'earliest 100', 'do not establish current acceptance']) expect(html).toContain(text)
    expect(html).not.toContain('Other association private reason')
    expect(html).toContain('<summary>Inspect recorded review decisions (1)</summary>')
    expect(html).toContain('dateTime="2026-10-25T01:30:00Z"')
  })
  it('does not infer never-reviewed from an empty association window', () => {
    expect(render({ loading: false, data: [] })).toContain('does not establish that it was never reviewed')
  })
  it('warns at the batch cap even when none of the loaded rows belongs to the selected association', () => {
    const data = Array.from({ length: 100 }, (_, n) => ({ ...row, id: String(n), association_id: 'association-b' }))
    const html = render({ loading: false, data })
    expect(html).toContain('Later decisions may be absent')
    expect(html).not.toContain(row.reason)
  })
  it.each([{ loading: true, data: [row] }, { loading: false, stale: true, data: [row] }, { loading: false, error: 'refused', data: [row] }, { loading: false }, { loading: false, data: Array(101).fill(row) }])('hides stale, unavailable or oversized history', resource => {
    expect(render(resource)).not.toContain(row.reason)
  })
  it('hides a previously loaded history when the current contact is refused', () => {
    expect(render({ loading: false, data: [row] }, false)).not.toContain(row.reason)
  })
  it('shows the current audited unlink action without inferring a new acceptance', () => {
    const html = render({ loading: false, data: [{ ...row, action: 'unlink' }] })
    expect(html).toContain('Recorded action: unlink')
    expect(html).toContain('do not establish current acceptance')
  })
  it('fails closed for malformed or unknown history records', () => {
    for (const patch of [{ action: 'unknown' }, { reason: null }, { expected_revision: -1 }, { id: null }]) {
      const html = render({ loading: false, data: [{ ...row, ...patch } as ReviewRecord] })
      expect(html).toContain('history is unavailable')
      expect(html).not.toContain(row.reason)
    }
  })
  it('escapes reasons and retains unknown time instead of inventing it', () => {
    const html = render({ loading: false, data: [{ ...row, reason: '<script>authored</script>', created_at: 'unknown' }] })
    expect(html).toContain('&lt;script&gt;authored&lt;/script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).toContain('Unknown time')
  })
  it('uses the explicit configured zone and labelled fallback', () => {
    expect(render({ loading: false, data: [row] }, true, row.association_id, 'Asia/Kolkata')).toContain('(Asia/Kolkata)')
    expect(render({ loading: false, data: [row] }, true, row.association_id, 'invalid-zone')).toContain('UTC fallback')
  })
  const contact = { organization_id: 'org-a', batch_id: 'batch-a', association_id: 'association-a' } as Contact
  it('requires matching current organization, batch and association before fetching history', () => {
    expect(currentHistoryContact({ loading: false, data: contact }, 'org-a', 'batch-a', 'association-a')).toBe(true)
    for (const values of [['org-b', 'batch-a', 'association-a'], ['org-a', 'batch-b', 'association-a'], ['org-a', 'batch-a', 'association-b']]) expect(currentHistoryContact({ loading: false, data: contact }, ...values as [string, string, string])).toBe(false)
    for (const resource of [{ loading: true, data: contact }, { loading: false, data: contact, stale: true }, { loading: false, data: contact, error: 'suppressed' }, { loading: false }]) expect(currentHistoryContact(resource, 'org-a', 'batch-a', 'association-a')).toBe(false)
  })
})
