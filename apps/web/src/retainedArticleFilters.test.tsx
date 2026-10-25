import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { ArticlePresenceFilter, ArticlePresenceHelp, articleSelectionParams } from './retainedArticleFilters'
import { Contacts } from './views'
import type { ArticleOutcomePresence } from './models'
import type { Context } from './ui'

const mock = vi.hoisted(() => ({ paths: [] as (string | null)[], pendingPaper: false }))
vi.mock('./ui', async importOriginal => ({
  ...await importOriginal<typeof import('./ui')>(),
  useSettledSearch: (_scope: unknown, value: string) => mock.pendingPaper && value ? null : value,
  useResource: (_scope: unknown, path: string | null) => { mock.paths.push(path); return { loading: false, data: { items: [], next_cursor: null } } },
}))
const job = '00000000-0000-4000-8000-000000000001'
const item = '00000000-0000-4000-8000-000000000002'
const values: ArticleOutcomePresence[] = ['all', 'observed_candidate', 'completed_without_candidate', 'unresolved']
beforeEach(() => { mock.paths = []; mock.pendingPaper = false })

describe('exact retained article selection', () => {
  it.each(['1', '10.9999/', '10.9999/../x', '10.9999/a\n', 'https://doi.org/10.9999/a'])('does not fetch or display results for an incomplete or unsupported DOI: %s', paper => {
    const scope = new ApiScope(job, 'synthetic-test-only')
    const context: Context = { scope, revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false, identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
    const html = renderToStaticMarkup(<Contacts context={context} review={false} filters={{ query: '', state: 'accepted', target: 'all', job: '', paper }} />)
    expect(mock.paths).toEqual([null, null])
    expect(html).toContain('Enter a supported bare DOI')
    expect(html).not.toContain('No contacts match')
    expect(html).not.toContain('No article outcomes')
  })
  it('disables both datasets while a valid edited DOI is settling, without fetching an unfiltered fallback', () => {
    mock.pendingPaper = true
    const scope = new ApiScope(job, 'synthetic-test-only')
    const context: Context = { scope, revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false, identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
    const html = renderToStaticMarkup(<Contacts context={context} review={false} filters={{ query: '', state: 'accepted', target: 'all', job: '', paper: '10.9999/synthetic.article-a' }} />)
    expect(mock.paths).toEqual([null, null])
    expect(html).not.toContain('No contacts match')
    expect(html).not.toContain('No article outcomes')
  })

  it('selects the same observed paper in both datasets without inventing a job or changing association state', () => {
    const scope = new ApiScope(job, 'synthetic-test-only')
    const context: Context = { scope, revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false, identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
    const paper = '10.9999/synthetic.article-a'
    const html = renderToStaticMarkup(<Contacts context={context} review={false} filters={{ query: '', state: 'accepted', target: 'all', job: '', paper }} />)
    for (const path of mock.paths) {
      const params = new URL(path!, 'https://synthetic.example').searchParams
      expect(params.get('paper_doi')).toBe(paper)
      expect(params.has('job_id')).toBe(false)
      expect(params.has('item_id')).toBe(false)
    }
    expect(new URL(mock.paths[0]!, 'https://synthetic.example').searchParams.get('state')).toBe('accepted')
    expect(html).toContain('Paper DOI (optional; across authorized jobs)')
    expect(articleSelectionParams(job, item, 'observed_candidate', paper)).toEqual({ job_id: job, item_id: item, article_outcome_presence: 'observed_candidate', paper_doi: paper })
  })
  it('keeps default requests byte-compatible and never sends an orphan item', () => {
    expect(articleSelectionParams()).toEqual({})
    expect(articleSelectionParams(null, item)).toEqual({})
    expect(articleSelectionParams(job, undefined, 'all')).toEqual({ job_id: job })
    expect(articleSelectionParams(job, item)).toEqual({ job_id: job, item_id: item })
  })
  it.each(values)('sends presence only to outcomes while selecting both datasets: %s', presence => {
    const scope = new ApiScope(job, 'synthetic-test-only')
    const context: Context = { scope, revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false, identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
    const html = renderToStaticMarkup(<Contacts context={context} review={false} filters={{ query: '', state: 'accepted', target: 'all', job, item, presence }} />)
    const contact = new URL(mock.paths[0]!, 'https://synthetic.example')
    const outcome = new URL(mock.paths[1]!, 'https://synthetic.example')
    for (const query of [contact.searchParams, outcome.searchParams]) {
      expect(query.get('job_id')).toBe(job)
      expect(query.get('item_id')).toBe(item)
      expect(query.get('limit')).toBe('25')
    }
    expect(contact.searchParams.has('article_outcome_presence')).toBe(false)
    expect(contact.searchParams.get('state')).toBe('accepted')
    expect(outcome.searchParams.get('article_outcome_presence')).toBe(presence === 'all' ? null : presence)
    expect(html).toContain('Article item UUID (optional; requires job)')
    expect(html).toContain('No contacts match these server filters.')
    expect(html).not.toContain('Evidence and review')
  })
  it('provides keyboard-native labeled choices with explicit outcome-only semantics', () => {
    const html = renderToStaticMarkup(<><ArticlePresenceFilter value="all" change={vi.fn()} /><ArticlePresenceHelp /></>)
    expect(html).toContain('Article-outcome candidate presence<select')
    for (const value of values) expect(html).toContain(`value="${value}"`)
    expect(html).toContain('only the separate article-outcome dataset')
    expect(html).toContain('invalid, unmatched or rejected')
    expect(html).toContain('unavailable or incomplete observations are unresolved')
  })
})
