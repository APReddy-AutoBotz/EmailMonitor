import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { basisLabel, defaultForm, discoverBody, documentQuery, OpenAccessWorkspace, outcomeLabel, splitAuthorNames, splitList } from './openAccess'
import type { Context } from './ui'

const org = '00000000-0000-4000-8000-000000000001'
function context(capabilities: string[] = ['source.acquire', 'results.export']): Context {
  const scope = new ApiScope(org, 'synthetic-only')
  return { scope, can: capability => capabilities.includes(capability), confirm: vi.fn(), act: vi.fn(), refresh: vi.fn(), identity: 'synthetic-only', zone: 'UTC', revision: 0, openJob: vi.fn() }
}

describe('open access request builders', () => {
  it('builds a bounded discovery body with deduplicated lists', () => {
    const body = discoverBody({ ...defaultForm, query: '  CRISPR  ', fromYear: '2024', untilYear: '2026', suppressedDomains: 'a.example\na.example, b.example', excludeJournals: 'X Journal;Y Journal' })
    expect(body).toEqual({ query: 'CRISPR', source: 'auto', max_results: 25, target_roles: 'both', from_year: 2024, until_year: 2026, exclude_journals: ['X Journal', 'Y Journal'], suppressed_emails: [], suppressed_domains: ['a.example', 'b.example'] })
  })
  it.each([
    [{ query: '' }, 'Enter a keyword'],
    [{ query: 'a'.repeat(1001) }, 'too long'],
    [{ query: 'CRI\u0000SPR' }, 'control characters'],
    [{ query: 'x', maxResults: 0 }, 'between 1 and 100'],
    [{ query: 'x', maxResults: 101 }, 'between 1 and 100'],
    [{ query: 'x', fromYear: '26' }, 'four-digit'],
    [{ query: 'x', fromYear: '2026', untilYear: '2020' }, 'must not be after'],
  ])('refuses invalid input %#', (patch, message) => {
    expect(() => discoverBody({ ...defaultForm, ...patch })).toThrow(message)
  })
  it('encodes document parameters and requires https page addresses', () => {
    expect(documentQuery('Ana Silva\nBen Ode', 'https://journal.example/a', 'all')).toBe('?target_roles=all&known_authors=Ana+Silva%3B+Ben+Ode&page_url=https%3A%2F%2Fjournal.example%2Fa')
    expect(documentQuery('', '', 'corresponding')).toBe('?target_roles=corresponding')
    expect(() => documentQuery('', 'http://journal.example/a', 'all')).toThrow('https://')
    expect(() => documentQuery('', 'javascript:alert(1)', 'all')).toThrow('https://')
  })
  it('keeps "Surname, Given" author names whole and in order', () => {
    expect(splitAuthorNames('Smith, John\nJones, Kate', 100)).toEqual(['Smith, John', 'Jones, Kate'])
    expect(documentQuery('Smith, John\nJones, Kate', '', 'all')).toBe('?target_roles=all&known_authors=Smith%2C+John%3B+Jones%2C+Kate')
  })
  it('caps list sizes', () => {
    expect(splitList(Array.from({ length: 60 }, (_, i) => 'j' + i).join('\n'), 50)).toHaveLength(50)
  })
  it('labels association bases and outcomes for operators', () => {
    expect(basisLabel('corresp_initials')).toBe('Shared note, matched by initials')
    expect(basisLabel('unmatched')).toBe('Not linked to an author')
    expect(basisLabel('future_basis')).toBe('future basis')
    expect(outcomeLabel('full_text_unavailable')).toBe('Own full text unavailable')
  })
})

describe('open access workspace rendering', () => {
  it('states the offline, no-guess boundary and offers every export preset', () => {
    const html = renderToStaticMarkup(<OpenAccessWorkspace context={context()} />)
    expect(html).toContain('Offline preview over committed synthetic fixtures')
    expect(html).toContain('nothing is guessed')
    for (const preset of ['Instantly', 'Smartlead', 'Lemlist', 'HubSpot', 'Evidence audit', 'Researchers (one row each)']) expect(html).toContain(preset)
    expect(html).toContain('Search fixtures')
  })
  it('disables discovery and export without the matching capabilities', () => {
    const html = renderToStaticMarkup(<OpenAccessWorkspace context={context(['organization.read'])} />)
    expect(html).toContain('Your role cannot run source discovery.')
    expect(html).toContain('Your role cannot export results.')
    expect(html).toMatch(/<button type="submit" disabled="">Search fixtures<\/button>/)
  })
})
