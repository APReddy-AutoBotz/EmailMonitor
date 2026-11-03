import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Item, Job, Progress } from './models'
import type { Context } from './ui'
import { Jobs } from './views'

const resources = vi.hoisted(() => ({ values: {} as Record<string, unknown> }))
vi.mock('./ui', async importOriginal => ({
  ...await importOriginal<typeof import('./ui')>(),
  useResource: (_scope: unknown, path: string | null) => ({ loading: false, data: path ? resources.values[path] : undefined }),
}))

const organization = '00000000-0000-0000-0000-000000000001'
const job: Job = { id: '00000000-0000-0000-0000-000000000002', kind: 'extraction', state: 'completed', row_version: 3, generation: 1, created_at: '2026-10-20T00:00:00Z', discovery_complete: true }
const item: Item = { id: '00000000-0000-0000-0000-000000000003', state: 'no_contact', reason: 'no_contact', work_kind: 'article', attempts: 1, batch_id: null }
const progress: Progress = { organization_id: organization, job_id: job.id, state: 'completed', revision: 3, generation: 1, discovery_pages: 0, source_reported_total: null, unique_articles: 1, duplicates: 0, discovery_complete: true, completeness: 'single_article', discovery_stop_reason: 'single_article',
  counts: { discovered: 1, pending: 0, active: 0, retry_wait: 0, terminal: 1, by_outcome: { no_contact: 1 } }, accepted_associations: 0, review_needed_associations: 0, progress_percent: 100, last_sequence: 3 }

function renderItems(items: Item[]) {
  resources.values = { '/jobs': [job], ['/jobs/' + job.id]: job, ['/jobs/' + job.id + '/progress']: progress, ['/jobs/' + job.id + '/progress/items']: items, ['/jobs/' + job.id + '/discovery']: {} }
  const context: Context = { scope: new ApiScope(organization, 'synthetic-test-only'), revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false, identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
  const request = vi.spyOn(context.scope, 'request')
  const html = renderToStaticMarkup(<Jobs context={context} selected={job.id} select={vi.fn()} />)
  expect(request).not.toHaveBeenCalled() // Authored render, never a browser or network receipt.
  return html
}
function outcomeCells(html: string): string[][] {
  const table = html.match(/<table><caption>Actual article outcomes and failures<\/caption>(.*?)<\/table>/s)?.[1]
  expect(table).toBeDefined()
  const headers = [...table!.matchAll(/<th>(.*?)<\/th>/gs)].map(match => match[1])
  expect(headers).toEqual(['Article', 'Outcome', 'Reason', 'Attempts'])
  expect([...table!.matchAll(/<tr>/g)]).toHaveLength(2)
  return [...table!.matchAll(/<tbody>(.*?)<\/tbody>/gs)].flatMap(body => [...body[1].matchAll(/<tr>(.*?)<\/tr>/gs)].map(row => [...row[1].matchAll(/<td>(.*?)<\/td>/gs)].map(cell => cell[1].replace(/<[^>]+>/g, ''))))
}

beforeEach(() => { resources.values = {}; vi.restoreAllMocks() })

describe('actual no-contact job outcome markup', () => {
  it('renders one article with separate no-contact Outcome and Reason cells', () => {
    const html = renderItems([item])
    expect(html).toContain('1 of 1 discovered article units terminal')
    const rows = outcomeCells(html)
    expect(rows).toEqual([[item.id + ' · article', 'no contact', 'no contact', '1']])
    // The old table-wide exact cell-name count of one rejected this correct row.
    expect(rows.flat().filter(cell => cell === 'no contact')).toHaveLength(2)
    expect(rows[0].slice(1, 3)).toEqual(['no contact', 'no contact'])
  })
  it.each([
    ['succeeded', 'no_contact', ['succeeded', 'no contact']],
    ['no_contact', 'observed', ['no contact', 'observed']],
  ])('does not manufacture the no-contact outcome from either field alone: %s / %s', (state, reason, expected) => {
    const rows = outcomeCells(renderItems([{ ...item, state, reason }]))
    expect(rows[0].slice(1, 3)).toEqual(expected)
    expect(rows[0].slice(1, 3)).not.toEqual(['no contact', 'no contact'])
  })
})
