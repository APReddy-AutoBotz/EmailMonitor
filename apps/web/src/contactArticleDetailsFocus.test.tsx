import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import { ContactArticleDetails } from './contactArticleDetails'
import type { Contact } from './models'

const hooks = vi.hoisted(() => ({ effect: undefined as undefined | (() => void | (() => void)) }))
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useRef: (initial: unknown) => ({ current: initial }),
  useLayoutEffect: (effect: () => void | (() => void)) => { hooks.effect = effect },
}))
beforeEach(() => { hooks.effect = undefined; vi.stubGlobal('document', { activeElement: {} }) })
afterEach(() => vi.unstubAllGlobals())

function setup(focusedInside: boolean) {
  const scope = new ApiScope('00000000-0000-4000-8000-000000000001', 'synthetic-only')
  const restore = vi.fn(), focus = vi.fn()
  const root = ContactArticleDetails({ scope, contact: { batch_id: 'batch' } as Contact, close: vi.fn(), restoreFocus: restore })
  const children = root.props.children as ReactNode[]
  const heading = children.find(child => isValidElement(child) && child.type === 'h4') as ReactElement<{ ref: { current: unknown } }>
  heading.props.ref.current = { focus }
  root.props.ref.current = { contains: () => focusedInside } as unknown as HTMLElement
  const cleanup = hooks.effect!()
  expect(focus).toHaveBeenCalledTimes(1)
  return { scope, restore, cleanup: cleanup as () => void }
}

describe('article details focus on invalidation', () => {
  it('moves focus to the fallback when a focused panel is invalidated', () => {
    const view = setup(true)
    view.cleanup()
    expect(view.restore).toHaveBeenCalledTimes(1)
  })
  it('does not steal focus when the user has already left the panel', () => {
    const view = setup(false)
    view.cleanup()
    expect(view.restore).not.toHaveBeenCalled()
  })
  it('does not move focus into a closed organization scope', () => {
    const view = setup(true)
    view.scope.close(); view.cleanup()
    expect(view.restore).not.toHaveBeenCalled()
  })
})
