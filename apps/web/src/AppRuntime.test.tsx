import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

// Exercise session establishment and optional profile effects without a DOM dependency.
const hooks = vi.hoisted(() => ({ values: [] as unknown[], index: 0, effects: [] as (() => (() => void) | void)[] }))
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial?: unknown) => {
    const index = hooks.index++
    if (!(index in hooks.values)) hooks.values[index] = typeof initial === 'function' ? initial() : initial
    return [hooks.values[index], (value: unknown) => { hooks.values[index] = typeof value === 'function' ? value(hooks.values[index]) : value }]
  },
  useRef: (initial: unknown) => ({ current: initial }),
  useEffect: (effect: () => (() => void) | void) => { hooks.effects.push(effect) },
}))
const identity = '00000000-0000-4000-8000-000000000001'
const session = { identity_id: identity, csrf_token: 'nonce', synthetic_only: true, production_enabled: false,
  memberships: [{ organization_id: identity, role: 'owner', organization_status: 'active', capabilities: ['organization.read'] }] }
const html = { profile: 'authored-html-service-reference', production_ready: false, xml_available: false,
  pdf_available: false, dynamic_browser_available: false, live_sources_available: false }
const xml = { ...html, profile: 'controlled-xml-service-reference', xml_available: true }
beforeEach(() => { hooks.values = []; hooks.index = 0; hooks.effects = [] })
afterEach(() => vi.unstubAllGlobals())

describe('session-established runtime discovery', () => {
  it.each([html, xml, undefined])('keeps an authenticated workspace for optional profile %j', async profile => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(session)))
      .mockResolvedValueOnce(profile ? new Response(JSON.stringify(profile)) : new Response('', { status: 404 }))
    vi.stubGlobal('fetch', fetcher)
    App(); const cleanup = hooks.effects[0]()
    await vi.waitFor(() => expect(hooks.values[2]).toBe(false))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    if (profile) await vi.waitFor(() => expect(hooks.values[5]).toEqual(profile))
    expect(hooks.values[0]).toEqual(session)
    expect(hooks.values[1]).toBeUndefined()
    expect(hooks.values[4]).toBe(identity)
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/v1/auth/session', '/api/v1/runtime-profile'])
    cleanup?.()
  })
  it('does not wait for the optional profile to open the workspace and ignores a cancelled late result', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(session)))
      .mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve })))
    App(); const cleanup = hooks.effects[0]()
    await vi.waitFor(() => expect(hooks.values[2]).toBe(false))
    expect(hooks.values[0]).toEqual(session)
    expect(hooks.values[5]).toBeUndefined()
    cleanup?.(); release(new Response(JSON.stringify(xml)))
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(hooks.values[5]).toBeUndefined()
  })
  it('does not read runtime metadata before a valid session', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetcher)
    App(); const cleanup = hooks.effects[0]()
    await vi.waitFor(() => expect(hooks.values[2]).toBe(false))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(hooks.values[0]).toBeUndefined()
    cleanup?.()
  })
})
