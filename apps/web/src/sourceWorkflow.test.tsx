import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { Contacts, Exports, Wizard } from './views'
import type { Context } from './ui'
const observed = vi.hoisted(() => ({ paths: [] as (string | null)[] }))
vi.mock('./ui', async original => ({ ...await original<typeof import('./ui')>(),
  useSettledSearch: (_: unknown, value: string) => value,
  useResource: (_: unknown, path: string | null) => {
    observed.paths.push(path)
    return { loading: false, data: path === '/sources' ? [{ source_id: 'synthetic-publisher', enabled: true, execution_mode: 'fixture' }] : path?.includes('/policies') || path === '/exports' ? [] : { items: [], next_cursor: null } }
  },
}))
const context = (): Context => ({ scope: new ApiScope('00000000-0000-4000-8000-000000000001', 'fixture-only'), revision: 0, act: vi.fn(), confirm: vi.fn(), can: () => true, refresh: vi.fn(), identity: 'fixture-only', zone: 'UTC', openJob: vi.fn(), openAcceptedSelection: vi.fn(), openExportSelection: vi.fn() })
const filters = { source: 'synthetic-publisher', job: '', state: 'accepted', query: '', target: 'all' }
beforeEach(() => { observed.paths = [] })
describe('connected source selector requests', () => {
  it('binds both retained datasets to the same source and removes it only on explicit clear', () => {
    renderToStaticMarkup(<Contacts context={context()} review={false} filters={filters} />)
    const paths = observed.paths.filter((p): p is string => !!p)
    expect(paths.some(p => p.startsWith('/contacts?'))).toBe(true)
    expect(paths.some(p => p.startsWith('/article-outcomes?'))).toBe(true)
    expect(paths.every(p => new URLSearchParams(p.split('?')[1]).get('source_id') === filters.source)).toBe(true)
    observed.paths = []
    renderToStaticMarkup(<Contacts context={context()} review={false} filters={{ ...filters, source: undefined }} />)
    expect(observed.paths.every(p => !p?.includes('source_id'))).toBe(true)
  })
  it('shows explicit source in export summary without carrying preview authorization', () => {
    const html = renderToStaticMarkup(<Exports context={context()} selection={filters} />)
    expect(html).toContain('source: synthetic-publisher')
    expect(html).toContain('value="synthetic-publisher" selected=""')
    expect(html).toContain('Preview eligible export counts')
    expect(html).not.toContain('Create asynchronous export')
  })
  it('uses a catalog-backed source control while missing approval still prevents planning', () => {
    const html = renderToStaticMarkup(<Wizard context={context()} />)
    expect(observed.paths).toContain('/sources')
    expect(html).toContain('Source<select required=""')
    expect(html).toContain('Synthetic Publisher · authored fixtures')
    expect(html).toContain('disabled="">Create and validate plan')
    expect(html).toContain('Availability')
    expect(html).toContain('Unknown; no live certification')
  })
})
