import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ApiScope } from './client'
import { ArticleDetailsGeneration, ContactArticleDetails, currentArticleSelection, type ArticleDetailsSelection } from './contactArticleDetails'
import type { Contact, Page } from './models'
import type { Resource } from './ui'

const org = '00000000-0000-4000-8000-000000000001'
const other = '00000000-0000-4000-8000-000000000002'
const contact = { organization_id: org, batch_id: 'batch-a', association_id: 'association-a', revision: 1 } as Contact
const page: Resource<Page<Contact>> = { loading: false, data: { items: [contact], next_cursor: null } }
const owner = new ApiScope(org, 'synthetic-only')
const selected: ArticleDetailsSelection = { scope: owner, generation: 4, contact }

describe('selected article details authorization and ownership', () => {
  it('does not revive an earlier selection after scope or filter returns', () => {
    const generations = new ArticleDetailsGeneration()
    const original = generations.observe(owner, 'accepted')
    generations.observe(owner, 'rejected')
    generations.observe(owner, 'accepted')
    expect(generations.current(original)).toBe(false)
    const second = generations.observe(owner, 'accepted')
    generations.observe(new ApiScope(org, 'synthetic-only'), 'accepted')
    generations.observe(owner, 'accepted')
    expect(generations.current(second)).toBe(false)
  })
  it('uses only a current matching contact and scope', () => {
    expect(currentArticleSelection(selected, owner, 4, page, false)).toBe(true)
    expect(currentArticleSelection(selected, new ApiScope(org, 'synthetic-only'), 4, page, false)).toBe(false)
    expect(currentArticleSelection(selected, new ApiScope(other, 'synthetic-only'), 4, page, false)).toBe(false)
    expect(currentArticleSelection(selected, owner, 5, page, false)).toBe(false)
    expect(currentArticleSelection(selected, owner, 4, page, true)).toBe(false)
  })
  it.each([
    { loading: true, data: page.data },
    { loading: false, error: 'refused', data: page.data },
    { loading: false, stale: true, data: page.data },
    { loading: false },
    { loading: false, data: { items: [], next_cursor: null } },
    { loading: false, data: { items: [{ ...contact, revision: 2 }], next_cursor: null } },
    { loading: false, data: { items: [{ ...contact, batch_id: 'batch-b' }], next_cursor: null } },
    { loading: false, data: { items: [{ ...contact, organization_id: other }], next_cursor: null } },
  ])('hides prior details when the contact page is missing, changed or refused', resource => {
    expect(currentArticleSelection(selected, owner, 4, resource, false)).toBe(false)
  })
  it('refuses a foreign selected record and a closed session', () => {
    expect(currentArticleSelection({ ...selected, contact: { ...contact, organization_id: other } }, owner, 4, page, false)).toBe(false)
    const closed = new ApiScope(org, 'synthetic-only')
    const selection = { ...selected, scope: closed }
    closed.close()
    expect(currentArticleSelection(selection, closed, 4, page, false)).toBe(false)
  })
  it('provides a focused, closable details region and makes no metadata claim while loading', () => {
    const html = renderToStaticMarkup(<ContactArticleDetails scope={owner} contact={contact} close={() => {}} restoreFocus={() => {}} />)
    expect(html).toContain('aria-label="Article details"')
    expect(html).toContain('tabindex="-1"')
    expect(html).toContain('Close article details')
    expect(html).toContain('Loading current article metadata')
    expect(html).not.toContain('Publication date unobserved')
  })
})
