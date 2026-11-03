import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Contact } from './models'
import { Load, type Context } from './ui'
import { EvidenceDrawer } from './views'

const hooks = vi.hoisted(() => ({ values: [] as unknown[], index: 0 }))
const fixtures = vi.hoisted(() => ({ contact: {} as Record<string, unknown>, bundle: {} as Record<string, unknown> }))
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useEffect: () => undefined,
  useState: (initial?: unknown) => { const i = hooks.index++; if (!(i in hooks.values)) hooks.values[i] = initial; return [hooks.values[i], (v: unknown) => { hooks.values[i] = v }] },
  useRef: (initial: unknown) => { const i = hooks.index++; if (!(i in hooks.values)) hooks.values[i] = { current: initial }; return hooks.values[i] },
}))
vi.mock('./ui', async original => ({ ...await original<typeof import('./ui')>(), useResource: (_: unknown, path: string) => ({ loading: false, data: path.startsWith('/contacts/') ? fixtures.contact : path.startsWith('/association-batches/') ? fixtures.bundle : { citation: { excerpt: 'Synthetic citation', method: 'fixture', locator: 'article' }, content_digest: 'a'.repeat(64) } }) }))

type Props = { children?: ReactNode | ((data: unknown) => ReactNode); resource?: { data?: unknown }; 'aria-label'?: string; type?: string; disabled?: boolean; onChange?: (event: { target: { value: string } }) => void; onSubmit?: (event: { preventDefault: () => void }) => void }
function elements(node: ReactNode): ReactElement<Props>[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Props>(node)) return []
  if (node.type === Load && typeof node.props.children === 'function') return elements(node.props.children(node.props.resource?.data))
  return [node, ...elements(node.props.children as ReactNode)]
}
function setup(review = true) {
  const org = '00000000-0000-4000-8000-000000000001', batch = '00000000-0000-4000-8000-000000000002', association = '00000000-0000-4000-8000-000000000003'
  const contact = { organization_id: org, batch_id: batch, association_id: association, revision: 3, author_id: 'author', evidence_ids: ['evidence'], raw_address: 'synthetic@example.org' } as Contact
  fixtures.contact = contact
  fixtures.bundle = { article_id: 'article', parser_version: 'fixture', observation_route: 'html', observation_status: 'observed', candidates: [], authors: [{ id: 'author', display_name: 'Synthetic author', position: 1, first: true, corresponding: true, affiliations: [] }], evidence: [{ id: 'evidence', method: 'fixture', excerpt: 'Synthetic citation', locator: 'article' }] }
  const scope = new ApiScope(org, 'synthetic-only'), write = vi.spyOn(scope, 'write').mockResolvedValue({})
  let pending: Promise<unknown> = Promise.resolve()
  const context: Context = { scope, revision: 0, refresh: vi.fn(), confirm: vi.fn(), identity: 'synthetic', zone: 'UTC', openJob: vi.fn(), can: capability => review && capability === 'association.review', act: vi.fn((_label, work) => { pending = work(); return pending.then(() => undefined) }) }
  const render = () => { hooks.index = 0; return EvidenceDrawer({ context, contact, close: vi.fn() }) }
  const change = (label: string, value: string) => { elements(render()).find(e => e.props['aria-label'] === label)!.props.onChange!({ target: { value } }) }
  const reason = (value: string) => { elements(render()).find(e => e.type === 'textarea')!.props.onChange!({ target: { value } }) }
  const submit = () => { elements(render()).find(e => e.type === 'form')!.props.onSubmit!({ preventDefault: vi.fn() }); return pending }
  return { render, change, reason, submit, write }
}
beforeEach(() => { hooks.values = []; hooks.index = 0; vi.restoreAllMocks() })
describe('unlink selected association', () => {
  it('uses the current revision and unchanged evidence with no author in the review request', async () => {
    const s = setup(); s.change('Review action', 'unlink'); s.reason('Synthetic review')
    const nodes = elements(s.render())
    expect(nodes.some(e => e.type === 'button' && e.props.children === 'Save review' && e.props.disabled)).toBe(false)
    await s.submit()
    expect(s.write).toHaveBeenCalledWith('/reviews', expect.objectContaining({ action: 'unlink', author_id: null, evidence_ids: ['evidence'], expected_revision: 3, reason: 'Synthetic review' }))
  })
  it('does not offer the action to read-only roles', () => {
    const s = setup(false)
    expect(elements(s.render()).some(e => e.props['aria-label'] === 'Review action')).toBe(false)
    expect(s.write).not.toHaveBeenCalled()
  })
})
