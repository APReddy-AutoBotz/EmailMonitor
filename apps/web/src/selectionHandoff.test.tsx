import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { acceptedSelection, selectionExport, selectionSummary, PreviewGeneration, type ContactFilters } from './selectionHandoff'
import { ApiScope } from './client'
import { Contacts, Exports } from './views'
import type { Context } from './ui'
vi.mock('./ui', async original => ({ ...await original<typeof import('./ui')>(), useSettledSearch: (_: unknown, value: string) => value, useResource: () => ({ loading: false }) }))
const job = '00000000-0000-4000-8000-000000000001', item = '00000000-0000-4000-8000-000000000002'
const selection: ContactFilters = { job, item, paper: '10.9999/synthetic.article-a', query: 'literal %_', target: 'corresponding', presence: 'observed_candidate', state: 'needs_review' }
const context = (allowed = true): Context => ({ scope: new ApiScope(job, 'fixture-only'), revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => allowed, identity: 'fixture-only', zone: 'UTC', openJob: vi.fn(), openAcceptedSelection: vi.fn(), openExportSelection: vi.fn() })
describe('accepted selection handoff', () => {
  it('explicitly changes review state, preserves selectors, and discards page/authorization extras', () => {
    const result = acceptedSelection({ ...selection, cursor: 'old-page', preview: { contacts: 99 }, include_unresolved: true } as ContactFilters)
    expect(result).toEqual({ ...selection, state: 'accepted' })
    const options = selectionExport(result!)!
    expect(options).toMatchObject({ job_id: job, item_id: item, paper_doi: selection.paper, query: selection.query, author_target: 'corresponding', article_outcome_presence: 'observed_candidate', include_unresolved: false })
    expect(options).not.toHaveProperty('cursor')
    expect(options).not.toHaveProperty('preview')
    expect(selectionSummary(options)).toContain('Accepted contacts')
    expect(selectionSummary(options)).toContain('Outcome-only')
  })
  it.each(['needs_review', 'unmatched', 'rejected', ''])('refuses direct export of state %s', state => {
    expect(selectionExport({ ...selection, state })).toBeUndefined()
  })
  it.each([{ job: 'partial' }, { item: 'partial' }, { job: '' }, { paper: '10.9999/' }, { query: 'a'.repeat(101) }, { target: 'unsupported' }])('does not broaden incomplete selection %j', patch => {
    expect(acceptedSelection({ ...selection, ...patch })).toBeUndefined()
    expect(selectionExport({ ...selection, state: 'accepted', ...patch })).toBeUndefined()
  })
  it('cleared selectors explicitly mean all authorized matching accepted results', () => {
    const options = selectionExport({ job: '', state: 'accepted', query: '', target: 'all' })!
    expect(options.job_id).toBeNull()
    expect(options.include_unresolved).toBe(false)
    expect(selectionSummary(options)).toContain('all authorized jobs')
  })
  it.each(['all', 'first', 'corresponding'])('preserves author selector %s', target => {
    expect(selectionExport({ ...selection, state: 'accepted', target })!.author_target).toBe(target)
  })
  it('requires export capability and accepted state for the native handoff button', () => {
    const html = (allowed: boolean, state: string) => renderToStaticMarkup(<Contacts context={context(allowed)} review={false} filters={{ ...selection, state }} />)
    expect(html(false, 'accepted')).not.toContain('Export this selection')
    expect(html(true, 'accepted')).toContain('>Export this selection</button>')
    expect(html(true, 'rejected')).toContain('disabled="">Export this selection')
  })
  it('offers a separately labeled accepted view from Review', () => {
    expect(renderToStaticMarkup(<Contacts context={context()} review filters={selection} />)).toContain('View accepted results for this selection')
  })
  it('renders carried selectors and explicit preview with no create authorization', () => {
    const html = renderToStaticMarkup(<Exports context={context()} selection={acceptedSelection(selection)} />)
    expect(html).toContain('Selection handoff')
    expect(html).toContain(selection.paper)
    expect(html).toContain('Preview eligible export counts')
    expect(html).not.toContain('Create asynchronous export')
    expect(html).not.toContain('checked=""/>Explicitly include unresolved')
  })
  it('refuses invalid handoff instead of showing an unfiltered form; honors capability', () => {
    expect(renderToStaticMarkup(<Exports context={context()} selection={selection} />)).not.toContain('Preview eligible export counts')
    expect(renderToStaticMarkup(<Exports context={context(false)} selection={acceptedSelection(selection)} />)).toContain('Export capability is not available')
  })
  it('rejects stale responses after edits, duplicate requests, clearing and teardown', () => {
    const owner = new PreviewGeneration(), first = owner.begin()
    owner.invalidate(); owner.invalidate() // A → B → A remains a new generation
    expect(owner.current(first)).toBe(false)
    const second = owner.begin(), third = owner.begin()
    expect(owner.current(second)).toBe(false)
    expect(owner.current(third)).toBe(true)
    owner.invalidate() // clear / unmount / session scope cleanup
    expect(owner.current(third)).toBe(false)
  })
})
