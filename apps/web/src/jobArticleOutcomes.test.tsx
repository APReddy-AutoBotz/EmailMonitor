import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { JobArticleOutcomes } from './jobArticleOutcomes'
import type { Outcome, Page } from './models'
import type { Context, Resource } from './ui'

const mock = vi.hoisted(() => ({ resource: { loading: false } as Resource<Page<Outcome>>, paths: [] as (string | null)[] }))
vi.mock('./ui', async importOriginal => ({
  ...await importOriginal<typeof import('./ui')>(),
  useResource: (_scope: unknown, path: string | null) => { mock.paths.push(path); return mock.resource },
}))
const organization = '00000000-0000-0000-0000-000000000001'
const job = '00000000-0000-0000-0000-000000000002'
const row: Outcome = {
  organization_id: organization, job_id: job, item_id: '00000000-0000-0000-0000-000000000003', source_url: 'https://synthetic.publisher.example/article-no-contact.html',
  state: 'no_contact', reason: 'observed', batch_id: '00000000-0000-0000-0000-000000000004', observation_status: 'no_contact', completed_at: '2026-10-20T00:00:00Z', inherited_job_id: null,
  technical_status: 'not_checked', outreach_eligibility: 'not_assessed',
}
function render(resource: Resource<Page<Outcome>>, closed = false) {
  mock.resource = resource
  const scope = new ApiScope(organization, 'synthetic-test-only')
  if (closed) scope.close()
  const context: Context = { scope, revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false, identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
  return renderToStaticMarkup(<JobArticleOutcomes context={context} job={job} />)
}
const success = (items: Outcome[] = [row], next_cursor: string | null = null): Resource<Page<Outcome>> => ({ loading: false, data: { items, next_cursor } })
beforeEach(() => { mock.paths = [] })

describe('job-scoped article outcomes', () => {
  it('requests the existing job-scoped endpoint at a bounded page size', () => {
    const html = render(success())
    expect(mock.paths).toEqual(['/article-outcomes?job_id=' + job + '&limit=25'])
    expect(html).toContain('Page 1: 1 article outcomes on this page.')
    expect(html).toContain('Page counts are not whole-job totals.')
    expect(html).toContain('Current-authorized article outcomes')
    expect(html).toContain(row.source_url)
    expect(html).toContain('Inspect article observation')
    expect(html).toContain('2026-10-20T00:00:00Z')
    expect(html).not.toContain('accepted association')
  })
  it('keeps outcome and reason independent and exposes no-contact batches without candidates', () => {
    const html = render(success())
    expect(html).toContain('status-no_contact')
    expect(html).toContain('<td>observed</td>')
    expect(html).toContain('Inspect article observation')
    expect(mock.paths).not.toContain('/contacts')
  })
  it('represents absent observation, time and batch without invented details', () => {
    const html = render(success([{ ...row, completed_at: null, observation_status: null, batch_id: null }]))
    expect(html).toContain('Completion time not recorded')
    expect(html).toContain('Observation status unavailable')
    expect(html).toContain('No retained observation batch')
    expect(html).not.toContain('Inspect article observation')
  })
  it('shows inherited job lineage only when the server supplies it', () => {
    expect(render(success())).toContain('Not inherited')
    expect(render(success([{ ...row, inherited_job_id: 'prior-synthetic-job' }]))).toContain('Inherited from job prior-synthetic-job')
  })
  it('identifies a reused observation and its original time without inventing lineage', () => {
    expect(render(success())).not.toContain('Reused observation')
    const html = render(success([{ ...row, observation_origin: 'reused', observed_at: '2026-10-01T13:00:00Z' }]))
    expect(html).toContain('Reused observation')
    expect(html).toContain('2026-10-01T13:00:00Z')
  })
  it('escapes source content rather than rendering or navigating to it', () => {
    const html = render(success([{ ...row, source_url: '<script>alert(1)</script>', reason: '<img src=x>' }]))
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(html).toContain('&lt;img src=x&gt;')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href=')
  })
  it('shows honest empty results with no forward paging', () => {
    const html = render(success([]))
    expect(html).toContain('No retained article outcomes for this job.')
    expect(html).toContain('Page 1: 0 article outcomes on this page.')
    expect(html).toContain('<button disabled="">Next article outcome page</button>')
  })
  it('enables forward paging only for a currently authorized cursor', () => {
    expect(render(success([row], 'opaque-next'))).toContain('<button>Next article outcome page</button>')
    expect(render(success())).toContain('<button disabled="">Next article outcome page</button>')
  })
  it.each([
    ['pending', { ...success([row], 'opaque-next'), loading: true }],
    ['failed', { ...success([row], 'opaque-next'), error: 'Resource unavailable' }],
    ['stale', { ...success([row], 'opaque-next'), stale: true }],
    ['missing', { loading: false }],
    ['wrong organization', success([{ ...row, organization_id: 'other-organization' }], 'opaque-next')],
    ['wrong job', success([{ ...row, job_id: 'other-job' }], 'opaque-next')],
  ] as const)('hides retained rows and forward cursor when %s', (_name, resource) => {
    const html = render(resource)
    expect(html).not.toContain(row.source_url)
    expect(html).not.toContain('Inspect article observation')
    expect(html).not.toContain('Current-authorized article outcomes')
    expect(html).toContain('<button disabled="">Next article outcome page</button>')
  })
  it('hides all rows for a closed organization scope', () => {
    const html = render(success(), true)
    expect(html).not.toContain(row.source_url)
    expect(html).toContain('Current article outcomes are unavailable.')
  })
})
