import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { optionalRuntimeProfile, RuntimeProfileNotice, validatedRuntimeProfile, type RuntimeProfile } from './runtimeProfile'

const html: RuntimeProfile = { profile: 'authored-html-service-reference', production_ready: false, xml_available: false,
  pdf_available: false, dynamic_browser_available: false, live_sources_available: false }
const xml: RuntimeProfile = { ...html, profile: 'controlled-xml-service-reference', xml_available: true }
afterEach(() => vi.unstubAllGlobals())

describe('optional installed runtime profile', () => {
  it.each([html, xml])('reads the bounded same-origin $profile without granting authority', async profile => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(profile)))
    vi.stubGlobal('fetch', fetcher)
    expect(await optionalRuntimeProfile(new AbortController().signal)).toEqual(profile)
    expect(fetcher).toHaveBeenCalledWith('/api/v1/runtime-profile', expect.objectContaining({
      credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    }))
  })
  it.each([401, 403, 404, 500])('does not disable the fixture application when optional endpoint returns %s', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('untrusted diagnostics', { status })))
    expect(await optionalRuntimeProfile(new AbortController().signal)).toBeUndefined()
  })
  it('tolerates unavailable transport and malformed responses without exposing details', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('private detail')).mockResolvedValueOnce(new Response('<html>not JSON</html>'))
    vi.stubGlobal('fetch', fetcher)
    expect(await optionalRuntimeProfile(new AbortController().signal)).toBeUndefined()
    expect(await optionalRuntimeProfile(new AbortController().signal)).toBeUndefined()
  })
  it('does not accept a late profile after cancellation even if fetch ignores abort', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { release = resolve })))
    const controller = new AbortController(), pending = optionalRuntimeProfile(controller.signal)
    controller.abort(); release(new Response(JSON.stringify(xml)))
    expect(await pending).toBeUndefined()
  })
  it('refuses inconsistent, unknown and capability-expanding profile payloads', () => {
    for (const value of [null, [], {}, { ...html, profile: 'live' }, { ...html, xml_available: true }, { ...xml, xml_available: false },
      ...['production_ready', 'pdf_available', 'dynamic_browser_available', 'live_sources_available'].map(key => ({ ...xml, [key]: true })),
      { ...xml, xml_available: 'true' }, { ...xml, live_sources_available: undefined }]) {
      expect(validatedRuntimeProfile(value)).toBeUndefined()
    }
  })
})

describe('installed capability and preflight notices', () => {
  it('makes the default HTML runtime refusal explicit', () => {
    const markup = renderToStaticMarkup(<RuntimeProfileNotice profile={html} preflight />)
    expect(markup).toContain('Runtime preflight')
    expect(markup).toContain('Controlled XML is unavailable')
    expect(markup).toContain('approving an XML policy does not enable XML execution')
  })
  it('keeps XML availability separate from explicit source policy and production readiness', () => {
    const markup = renderToStaticMarkup(<RuntimeProfileNotice profile={xml} preflight />)
    expect(markup).toContain('separate, explicitly approved synthetic XML source policy')
    expect(markup).toContain('does not grant source permission')
    expect(markup).toContain('PDF, dynamic browser and live sources are unavailable')
    expect(markup).toContain('not production-ready')
    expect(markup).toContain('Server planning and launch checks remain authoritative')
    expect(markup).toContain('review and export permissions are unchanged')
    expect(markup).not.toContain('<button')
  })
  it('makes missing capabilities unverified, never a synthetic app blocker or capability promise', () => {
    expect(renderToStaticMarkup(<RuntimeProfileNotice />)).toBe('')
    const markup = renderToStaticMarkup(<RuntimeProfileNotice preflight />)
    expect(markup).toContain('capabilities are unverified')
    expect(markup).toContain('Existing fixture planning remains available')
    expect(markup).not.toContain('XML is available')
    expect(markup).not.toContain('<button')
  })
})
