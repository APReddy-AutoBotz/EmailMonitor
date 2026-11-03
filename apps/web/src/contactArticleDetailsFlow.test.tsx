import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { ContactArticleDetails } from './contactArticleDetails'
import type { Contact, Page } from './models'
import type { ContactFilters } from './selectionHandoff'
import { Load, type Context, type Resource } from './ui'
import { Contacts } from './views'

const hooks = vi.hoisted(() => ({ values: [] as unknown[], index: 0 }))
const fixture = vi.hoisted(() => ({ contacts: { loading: false } as Resource<Page<Contact>> }))
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useState: (initial?: unknown) => {
    const index = hooks.index++
    if (!(index in hooks.values)) hooks.values[index] = initial
    return [hooks.values[index], (value: unknown) => { hooks.values[index] = typeof value === 'function' ? value(hooks.values[index]) : value }]
  },
  useRef: (initial: unknown) => {
    const index = hooks.index++
    if (!(index in hooks.values)) hooks.values[index] = { current: initial }
    return hooks.values[index]
  },
  useEffect: vi.fn(),
}))
vi.mock('./ui', async original => ({
  ...await original<typeof import('./ui')>(),
  useSettledSearch: (_: unknown, value: string) => value,
  useResource: (_: unknown, path: string | null) => path?.startsWith('/contacts?') ? fixture.contacts : { loading: false, data: { items: [], next_cursor: null } },
}))

type Props = { children?: ReactNode | ((data: unknown) => ReactNode); resource?: Resource<unknown>; disabled?: boolean; onClick?: () => void; ref?: (node: HTMLButtonElement | null) => void; close?: () => void; contact?: Contact; 'aria-expanded'?: boolean; 'aria-label'?: string }
function elements(node: ReactNode): ReactElement<Props>[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Props>(node)) return []
  if (node.type === Load && node.props.resource?.data !== undefined && typeof node.props.children === 'function') {
    return [node, ...elements(node.props.children(node.props.resource.data))]
  }
  return [node, ...elements(typeof node.props.children === 'function' ? null : node.props.children)]
}
const org = '00000000-0000-4000-8000-000000000001'
const batch = '00000000-0000-4000-8000-000000000002'
const association = '00000000-0000-4000-8000-000000000003'
const row: Contact = { organization_id: org, job_id: org, batch_id: batch, association_id: association, revision: 1, author_id: null, author_name: 'Synthetic author', raw_address: 'fixture@example.invalid', normalized_address: 'fixture@example.invalid', state: 'accepted', first_author: true, corresponding_author: false, affiliations: [], title: 'Authored title', evidence_ids: [], evidence_strength: 'explicit', source_url: 'https://synthetic.publisher.example/article-a.html', policy_version: 1, observed_at: '2026-10-01T00:00:00Z', identity_state: 'article_local_unresolved', syntax_status: 'valid', technical_status: 'not_checked', delivery_status: 'unverified', outreach_eligibility: 'not_assessed' }
const filters: ContactFilters = { query: '', state: 'accepted', target: 'all', job: '' }
beforeEach(() => { hooks.values = []; hooks.index = 0; fixture.contacts = { loading: false, data: { items: [row], next_cursor: 'next-page' } } })

function setup() {
  const scope = new ApiScope(org, 'synthetic-only')
  const context: Context = { scope, revision: 0, can: () => true, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), identity: 'synthetic-only', zone: 'UTC', openJob: vi.fn() }
  const render = (currentFilters = filters) => { hooks.index = 0; return elements(Contacts({ context, review: false, filters: currentFilters })) }
  const button = (label: string) => render().find(element => element.type === 'button' && element.props.children === label)!
  const panel = () => render().find(element => element.type === ContactArticleDetails)
  return { scope, context, render, button, panel }
}

describe('on-demand article details from current contact results', () => {
  it('opens one selected row and restores keyboard focus when closed', () => {
    const view = setup()
    const opener = { isConnected: true, focus: vi.fn() } as unknown as HTMLButtonElement
    expect(view.button('View article details').props['aria-label']).toBe('View article details for Authored title')
    view.button('View article details').props.ref!(opener)
    view.button('View article details').props.onClick!()
    expect(view.panel()?.props.contact).toEqual(row)
    expect(view.button('View article details').props['aria-expanded']).toBe(true)
    view.panel()!.props.close!()
    expect(view.panel()).toBeUndefined()
    expect(opener.focus).toHaveBeenCalledTimes(1)
  })
  it('replaces the prior selection when another contact is chosen', () => {
    const second = { ...row, batch_id: '00000000-0000-4000-8000-000000000004', association_id: '00000000-0000-4000-8000-000000000005' }
    fixture.contacts = { loading: false, data: { items: [row, second], next_cursor: null } }
    const view = setup()
    const openers = () => view.render().filter(element => element.type === 'button' && element.props.children === 'View article details')
    openers()[0].props.onClick!()
    expect(view.panel()?.props.contact).toEqual(row)
    openers()[1].props.onClick!()
    expect(view.panel()?.props.contact).toEqual(second)
    expect(view.render().filter(element => element.type === ContactArticleDetails)).toHaveLength(1)
  })
  it('hides details on filter changes, including returning to an earlier selection', () => {
    const view = setup()
    view.button('View article details').props.onClick!()
    expect(view.panel()).toBeDefined()
    view.render({ ...filters, state: 'rejected' })
    expect(view.render().some(element => element.type === ContactArticleDetails)).toBe(false)
  })
  it('hides details on pagination, refresh, stale response or session close', () => {
    const view = setup()
    view.button('View article details').props.onClick!()
    view.button('Next contact page').props.onClick!()
    expect(view.panel()).toBeUndefined()
    view.button('View article details').props.onClick!()
    view.context.revision += 1
    expect(view.panel()).toBeUndefined()
    view.button('View article details').props.onClick!()
    fixture.contacts = { ...fixture.contacts, stale: true }
    expect(view.panel()).toBeUndefined()
    fixture.contacts = { loading: false, data: { items: [row], next_cursor: null } }
    view.scope.close()
    expect(view.panel()).toBeUndefined()
  })
  it('does not revive details after replacing and restoring the organization scope', () => {
    const view = setup()
    view.button('View article details').props.onClick!()
    const previous = view.context.scope
    view.context.scope = new ApiScope(org, 'synthetic-only')
    expect(view.panel()).toBeUndefined()
    view.context.scope = previous
    expect(view.panel()).toBeUndefined()
  })
  it('does not open a foreign-organization contact or stale revision', () => {
    fixture.contacts = { loading: false, data: { items: [{ ...row, organization_id: '00000000-0000-4000-8000-000000000099' }], next_cursor: null } }
    const view = setup()
    expect(view.button('View article details').props.disabled).toBe(true)
    view.button('View article details').props.onClick!()
    expect(view.panel()).toBeUndefined()
  })
  it('closes article details when opening the existing evidence review', () => {
    const view = setup()
    view.button('View article details').props.onClick!()
    expect(view.panel()).toBeDefined()
    view.button('Evidence and review').props.onClick!()
    expect(view.panel()).toBeUndefined()
  })
})
