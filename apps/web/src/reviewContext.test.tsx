import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Contact } from './models'
import { currentContext, ReviewContext } from './reviewContext'

const hooks = vi.hoisted(() => ({ values: [] as unknown[], index: 0 }))
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useEffect: () => undefined,
  useState: (initial?: unknown) => { const i = hooks.index++; if (!(i in hooks.values)) hooks.values[i] = initial; return [hooks.values[i], (value: unknown) => { hooks.values[i] = value }] },
  useRef: (initial: unknown) => { const i = hooks.index++; if (!(i in hooks.values)) hooks.values[i] = { current: initial }; return hooks.values[i] },
}))

type Props = { children?: ReactNode; value?: string; onChange?: (event: { target: { value: string } }) => void; onSubmit?: (event: { preventDefault: () => void }) => void; onClick?: () => void }
function elements(node: ReactNode): ReactElement<Props>[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Props>(node)) return []
  return [node, ...elements(node.props.children)]
}
const org = '00000000-0000-4000-8000-000000000001'
const batch = '00000000-0000-4000-8000-000000000002'
const source = '00000000-0000-4000-8000-000000000003'
const citation = '00000000-0000-4000-8000-000000000004'
const association = '00000000-0000-4000-8000-000000000005'
const target = { organization_id: org, batch_id: batch, association_id: association, revision: 2 } as Contact
const reply = { kind: 'transient_context_only', organization_id: org, target_batch_id: batch, target_association_id: association, target_revision: 2, source_batch_id: source, source_url: 'https://synthetic.publisher.example/article-b.html', source_digest: 'a'.repeat(64), source_parser_version: 'fixture', source_route: 'html', evidence: { id: citation, method: 'article_dom', locator: 'article', excerpt: 'Authored citation', page: null }, attached: false, identity_verified: false, acceptance_changed: false, export_changed: false }
beforeEach(() => { hooks.values = []; hooks.index = 0; vi.restoreAllMocks() })

describe('temporary review context', () => {
  it('requires matching scope, target revision and a non-mutating response', () => {
    const scope = new ApiScope(org, 'synthetic')
    expect(currentContext(reply, scope, target, source, citation)).toBe(true)
    for (const change of [{ attached: true }, { identity_verified: true }, { export_changed: true }, { target_revision: 1 }, { source_batch_id: batch }, { organization_id: batch }]) {
      expect(currentContext({ ...reply, ...change }, scope, target, source, citation)).toBe(false)
    }
    scope.close()
    expect(currentContext(reply, scope, target, source, citation)).toBe(false)
  })
  it('renders fixed non-attachment explanation and never sends invented evidence', async () => {
    const scope = new ApiScope(org, 'synthetic'), write = vi.spyOn(scope, 'write').mockResolvedValue(reply)
    const render = () => { hooks.index = 0; return elements(ReviewContext({ scope, target })) }
    let inputs = render().filter(row => row.type === 'input')
    inputs[0].props.onChange!({ target: { value: source } }); inputs = render().filter(row => row.type === 'input')
    inputs[1].props.onChange!({ target: { value: citation } })
    render().find(row => row.type === 'form')!.props.onSubmit!({ preventDefault: vi.fn() })
    await Promise.resolve(); await Promise.resolve()
    expect(write).toHaveBeenCalledWith('/review-context/view', { target_batch_id: batch, target_association_id: association, expected_revision: 2, source_batch_id: source, source_evidence_id: citation })
    expect(render().some(row => row.type === 'blockquote' && row.props.children === 'Authored citation')).toBe(true)
    expect(render().some(row => typeof row.props.children === 'string' && row.props.children.includes('not attached or saved'))).toBe(true)
  })
  it('ignores a delayed response after the selected source is changed', async () => {
    const scope = new ApiScope(org, 'synthetic')
    let resolve!: (value: unknown) => void
    vi.spyOn(scope, 'write').mockReturnValue(new Promise(done => { resolve = done }))
    const render = () => { hooks.index = 0; return elements(ReviewContext({ scope, target })) }
    render().filter(row => row.type === 'input')[0].props.onChange!({ target: { value: source } })
    render().filter(row => row.type === 'input')[1].props.onChange!({ target: { value: citation } })
    render().find(row => row.type === 'form')!.props.onSubmit!({ preventDefault: vi.fn() })
    render().filter(row => row.type === 'input')[0].props.onChange!({ target: { value: batch } })
    resolve(reply); await Promise.resolve(); await Promise.resolve()
    expect(render().some(row => row.type === 'blockquote')).toBe(false)
  })
})
