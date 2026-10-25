import { Children, isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Contact } from './models'
import type { Context } from './ui'
import { EvidenceDrawer } from './views'

const fixtures = vi.hoisted(() => ({
  contact: { association_id: '00000000-0000-4000-8000-000000000001', batch_id: '00000000-0000-4000-8000-000000000002', evidence_ids: ['00000000-0000-4000-8000-000000000003'], author_id: null },
  bundle: { candidates: [], authors: [], evidence: [] },
}))
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => [initial, vi.fn()],
  useRef: (initial: unknown) => ({ current: initial }),
  useEffect: vi.fn(),
}))
vi.mock('./ui', async original => ({
  ...await original<typeof import('./ui')>(),
  useResource: (_scope: unknown, path: string) => ({ loading: false, data: path.startsWith('/association-batches/') ? fixtures.bundle : fixtures.contact }),
}))
beforeEach(() => vi.restoreAllMocks())

function find(node: ReactNode, tag: string): ReactElement<Record<string, unknown>> {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<Record<string, unknown>>(child)) continue
    if (child.type === tag) return child
    try { return find(child.props.children as ReactNode, tag) } catch { /* Try the next child. */ }
  }
  throw new Error(`Missing authored ${tag}`)
}

function setup(denied = false) {
  const scope = new ApiScope(fixtures.contact.association_id, 'synthetic-test-only')
  const write = vi.spyOn(scope, 'write')
  if (denied) write.mockRejectedValue(new Error('authored refusal'))
  else write.mockResolvedValue(undefined)
  let selected = true, connected = true, reopened = false
  let action: Promise<void> | undefined
  const close = vi.fn(() => { selected = false })
  const queued: (() => void)[] = []
  const refresh = vi.fn(() => { connected = false; reopened = selected })
  const context: Context = { scope, revision: 0, can: () => true, refresh,
    act: (_label, work) => { action = (async () => { try { await work(); refresh() } catch { /* The real workspace preserves the refusal. */ } })(); return action },
    confirm: vi.fn(), identity: 'synthetic-test-only', zone: 'UTC', openJob: vi.fn() }
  const root = EvidenceDrawer({ context, contact: fixtures.contact as Contact, close })
  const nativeClose = vi.fn(() => { queued.push(() => { if (connected) root.props.onClose() }) })
  root.props.ref.current = { close: nativeClose }
  const load = Children.toArray(root.props.children).find(child => isValidElement<{ resource?: { data: unknown } }>(child) && child.props.resource?.data === fixtures.bundle) as ReactElement<{ children: (data: unknown) => ReactNode }>
  const form = find(load.props.children(fixtures.bundle), 'form')
  return { close, refresh, nativeClose, root, write,
    async save() { (form.props.onSubmit as (event: { preventDefault: () => void }) => void)({ preventDefault: vi.fn() }); await action },
    flush() { queued.splice(0).forEach(event => event()) },
    reopened: () => reopened,
  }
}

describe('evidence selection across asynchronous native close and workspace refresh', () => {
  it('clears selection before successful review refresh can unmount the queued close event', async () => {
    const state = setup()
    await state.save()
    state.flush() // The detached native close event cannot reach the mounted React handler.
    expect(state.write).toHaveBeenCalledTimes(1)
    expect(state.refresh).toHaveBeenCalledTimes(1)
    expect(state.reopened()).toBe(false)
    expect(state.close).toHaveBeenCalledTimes(1)
  })
  it('does not close or refresh when the review is refused', async () => {
    const state = setup(true)
    await state.save(); state.flush()
    expect(state.nativeClose).not.toHaveBeenCalled()
    expect(state.close).not.toHaveBeenCalled()
    expect(state.refresh).not.toHaveBeenCalled()
  })
  it('closes once synchronously for the button and ignores a late native close delivery', () => {
    const state = setup()
    const button = find(state.root.props.children, 'button')
    ;(button.props.onClick as () => void)()
    expect(state.close).toHaveBeenCalledTimes(1)
    state.flush(); state.root.props.onClose()
    expect(state.close).toHaveBeenCalledTimes(1)
    expect(state.nativeClose).toHaveBeenCalledTimes(1)
  })
  it('retains native Escape close handling without another native close request', () => {
    const state = setup()
    state.root.props.onClose()
    expect(state.close).toHaveBeenCalledTimes(1)
    expect(state.nativeClose).not.toHaveBeenCalled()
  })
})
