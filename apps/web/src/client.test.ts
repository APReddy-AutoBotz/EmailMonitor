import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, ApiScope, readBounded, sessionRequest } from './client'
const org = '00000000-0000-4000-8000-000000000001'
const other = '00000000-0000-4000-8000-000000000002'
const job = '00000000-0000-4000-8000-000000000003'
afterEach(() => vi.unstubAllGlobals())
describe('current organization transport', () => {
  it('requires canonical scope and refuses escaping paths', () => {
    expect(() => new ApiScope('untrusted', 'nonce')).toThrow(ApiError)
    const scope = new ApiScope(org, 'nonce')
    expect(scope.path('/')).toBe('/api/v1/organizations/' + org)
    for (const path of ['//other.invalid', '/../' + other + '/jobs', '/../../auth/session', 'https://other.invalid', '/jobs#secret']) expect(() => scope.path(path)).toThrow(ApiError)
    scope.close()
  })
  it('forces same origin, no redirects, current nonce and no cache', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetcher)
    const scope = new ApiScope(org, 'nonce')
    await scope.write('/jobs', {}, 'POST', 'idempotency')
    const [path, options] = fetcher.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/v1/organizations/' + org + '/jobs')
    expect(options.credentials).toBe('same-origin'); expect(options.redirect).toBe('error'); expect(options.cache).toBe('no-store')
    expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('nonce')
    expect(new Headers(options.headers).get('Idempotency-Key')).toBe('idempotency')
    scope.close()
  })
  it('refuses late old-tenant response even when a transport ignores abort', async () => {
    let release!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { release = resolve })))
    const scope = new ApiScope(org, 'nonce'), pending = scope.request('/jobs')
    scope.close(); release(new Response('{"old":"tenant"}'))
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
  it('refuses late body data after organization switch', async () => {
    let release!: ReadableStreamDefaultController<Uint8Array>
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(controller) { release = controller } }))))
    const scope = new ApiScope(org, 'nonce'), pending = scope.request('/jobs')
    await Promise.resolve(); await Promise.resolve()
    scope.close(); release.enqueue(new TextEncoder().encode('{}')); release.close()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
  it('conceals arbitrary server error text and reports expired sessions', async () => {
    const expired = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private diagnostic', { status: 401 })))
    const scope = new ApiScope(org, 'nonce', expired)
    await expect(scope.request('/jobs')).rejects.toMatchObject({ status: 401, message: 'Your session ended. Sign in again.' })
    expect(expired).toHaveBeenCalledOnce(); scope.close()
  })
})
describe('bounded response and scoped replay', () => {
  it('refuses excess bytes and malformed UTF8 rather than truncating', async () => {
    await expect(readBounded(new Response('12345'), 4)).rejects.toThrow('supported size')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([255]))))
    const scope = new ApiScope(org, 'nonce')
    await expect(scope.request('/jobs')).rejects.toThrow(); scope.close()
  })
  const frame = (tenant = org, sequence = 1) => `id: opaque-${sequence}\ndata: ${JSON.stringify({ organization_id: tenant, job_id: job, sequence, event_type: 'item.completed' })}\n\n`
  it('retains a validated incremental checkpoint when a stream fails before EOF', async () => {
    let source!: ReadableStreamDefaultController<Uint8Array>
    const stream = new ReadableStream<Uint8Array>({ start(controller) { source = controller } })
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(stream, { headers: { 'content-type': 'text/event-stream' } })).mockResolvedValueOnce(new Response(frame(org, 2), { headers: { 'content-type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetcher)
    const scope = new ApiScope(org, 'nonce'), delivered = vi.fn()
    let checkpoint = ''
    let ready!: () => void
    const observed = new Promise<void>(resolve => { ready = resolve })
    const interrupted = scope.events(job, (event, id) => { delivered(event); checkpoint = id; ready() }, new AbortController().signal, checkpoint)
    const refused = expect(interrupted).rejects.toMatchObject({ name: 'AbortError' })
    source.enqueue(new TextEncoder().encode(frame()))
    await observed
    expect(checkpoint).toBe('opaque-1')
    source.error(new DOMException('Connection timed out', 'AbortError'))
    await refused
    checkpoint = await scope.events(job, (event, id) => { delivered(event); checkpoint = id }, new AbortController().signal, checkpoint)
    expect(new Headers((fetcher.mock.calls[1] as [string, RequestInit])[1].headers).get('Last-Event-ID')).toBe('opaque-1')
    expect(checkpoint).toBe('opaque-2'); expect(delivered).toHaveBeenCalledTimes(2)
    scope.close()
  })
  it('never checkpoints an unvalidated other-tenant frame', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(frame(other), { headers: { 'content-type': 'text/event-stream' } })))
    const scope = new ApiScope(org, 'nonce'), checkpoint = vi.fn()
    await expect(scope.events(job, checkpoint, new AbortController().signal, 'existing')).rejects.toThrow('Unexpected scoped event')
    expect(checkpoint).not.toHaveBeenCalled(); scope.close()
  })
  it('sends opaque Last-Event-ID and processes only scoped events', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(frame(), { headers: { 'content-type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetcher)
    const scope = new ApiScope(org, 'nonce'), received = vi.fn()
    expect(await scope.events(job, received, new AbortController().signal, 'previous')).toBe('opaque-1')
    expect(received).toHaveBeenCalledOnce()
    expect(new Headers((fetcher.mock.calls[0] as [string, RequestInit])[1].headers).get('Last-Event-ID')).toBe('previous'); scope.close()
  })
  it.each([frame(other), frame() + frame(), 'data: {}\n\n'])('rejects wrong scope, nonadvancing or unidentified events', async value => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(value, { headers: { 'content-type': 'text/event-stream' } })))
    const scope = new ApiScope(org, 'nonce')
    await expect(scope.events(job, vi.fn(), new AbortController().signal)).rejects.toThrow(ApiError); scope.close()
  })
  it('does not dispatch stream events after scope closes', async () => {
    const scope = new ApiScope(org, 'nonce'); scope.close()
    const received = vi.fn()
    await expect(scope.events(job, received, new AbortController().signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(received).not.toHaveBeenCalled()
  })
  it('does not admit arbitrary session routes', async () => {
    await expect(sessionRequest('/organizations/' + other)).rejects.toThrow(ApiError)
  })
})
