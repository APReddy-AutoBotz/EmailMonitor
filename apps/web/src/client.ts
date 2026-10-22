/** Same-origin, bounded, abortable transport. Tenant scope never survives a switch. */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}
export const errorMessage = (error: unknown): string => {
  if (error instanceof ApiError) return error.message
  return 'The service could not be reached. Check the connection and retry.'
}
const messageFor = (status: number): string => status === 401 ? 'Your session ended. Sign in again.'
  : status === 403 ? 'This action is not permitted.' : status === 404 ? 'Resource unavailable. Permissions or retention may have changed.'
  : status === 409 ? 'The data changed or a dependency is unavailable. Refresh before retrying.'
  : status === 422 ? 'Check the supplied fields. This fixture may not support that input.' : 'The request could not be completed.'

export async function readBounded(response: Response, maximum = 2 * 1024 * 1024): Promise<Uint8Array> {
  if (!response.body) return new Uint8Array()
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let length = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.length
      if (length > maximum) { await reader.cancel(); throw new ApiError(0, 'Response exceeded the supported size.') }
      chunks.push(value)
    }
  } finally { reader.releaseLock() }
  const all = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.length }
  return all
}
export async function sessionRequest<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!['/auth/session', '/auth/callback', '/capabilities', '/runtime-profile'].includes(path.split('?')[0])) throw new ApiError(0, 'Unsupported session route.')
  const controller = new AbortController(), abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  const timer = setTimeout(abort, 20000)
  try {
    const response = await fetch('/api/v1' + path, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal, headers: { 'X-EmailMonitor-UI': 'session' } })
    if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status, messageFor(response.status)) }
    const bytes = await readBounded(response)
    if (controller.signal.aborted) throw new DOMException('Session request ended', 'AbortError')
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as T
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort) }
}
export type LiveEvent = { organization_id: string; job_id: string; sequence: number; event_type: string }
export class ApiScope {
  readonly controller = new AbortController()
  constructor(readonly organization: string, readonly csrf: string, readonly onExpired: () => void = () => {}) {
    if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(organization)) throw new ApiError(0, 'Invalid organization scope.')
  }
  get closed() { return this.controller.signal.aborted }
  close() { this.controller.abort() }
  path(suffix: string): string {
    const base = '/api/v1/organizations/' + this.organization
    if (!suffix.startsWith('/') || suffix.startsWith('//') || suffix.includes('#')) throw new ApiError(0, 'Invalid scoped route.')
    const parsed = new URL(base + suffix, 'https://application.invalid')
    if (parsed.origin !== 'https://application.invalid' || !parsed.pathname.startsWith(base + '/')) throw new ApiError(0, 'Scoped route escaped its organization.')
    return (suffix === '/' ? base : parsed.pathname) + parsed.search
  }
  async response(suffix: string, init: RequestInit = {}, stream = false): Promise<Response> {
    if (this.closed) throw new DOMException('Organization changed', 'AbortError')
    const controller = new AbortController()
    const abort = () => controller.abort()
    this.controller.signal.addEventListener('abort', abort, { once: true })
    init.signal?.addEventListener('abort', abort, { once: true })
    if (init.signal?.aborted) abort()
    const timer = setTimeout(abort, stream ? 30000 : 20000)
    try {
      const headers = new Headers(init.headers)
      if (init.method && init.method !== 'GET') {
        headers.set('X-CSRF-Token', this.csrf)
        headers.set('Content-Type', 'application/json')
      }
      const response = await fetch(this.path(suffix), { ...init, headers, signal: controller.signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
      if (this.closed || controller.signal.aborted) throw new DOMException('Organization changed', 'AbortError')
      if (!response.ok) { await response.body?.cancel(); if (response.status === 401) this.onExpired(); throw new ApiError(response.status, messageFor(response.status)) }
      // The consumer must retain cancellation through body reads, not just headers.
      const cleanup = () => { clearTimeout(timer); this.controller.signal.removeEventListener('abort', abort); init.signal?.removeEventListener('abort', abort) }
      if (!response.body) { cleanup(); return response }
      const reader = response.body.getReader()
      const body = new ReadableStream<Uint8Array>({
        async pull(target) { try { const row = await reader.read(); if (row.done) { cleanup(); reader.releaseLock(); target.close() } else target.enqueue(row.value) } catch (error) { cleanup(); reader.releaseLock(); target.error(error) } },
        async cancel(reason) { cleanup(); await reader.cancel(reason); reader.releaseLock() },
      })
      return new Response(body, { status: response.status, headers: response.headers })
    } catch (error) {
      clearTimeout(timer); this.controller.signal.removeEventListener('abort', abort); init.signal?.removeEventListener('abort', abort)
      throw error
    }
  }
  async request<T>(suffix: string, init: RequestInit = {}): Promise<T> {
    const response = await this.response(suffix, init)
    const bytes = await readBounded(response)
    if (this.closed || init.signal?.aborted) throw new DOMException('Organization changed', 'AbortError')
    return bytes.length ? JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as T : undefined as T
  }
  write<T>(suffix: string, body: unknown, method = 'POST', key?: string): Promise<T> {
    return this.request<T>(suffix, { method, body: JSON.stringify(body), headers: key ? { 'Idempotency-Key': key } : {} })
  }
  async events(job: string, onEvent: (event: LiveEvent, cursor: string) => void, signal: AbortSignal, cursor = ''): Promise<string> {
    const response = await this.response('/jobs/' + encodeURIComponent(job) + '/events', { signal, headers: cursor ? { 'Last-Event-ID': cursor } : {} }, true)
    if (!response.headers.get('content-type')?.startsWith('text/event-stream') || !response.body) { await response.body?.cancel(); throw new ApiError(0, 'Unexpected event stream.') }
    const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', { fatal: true })
    let pending = '', total = 0, last = cursor, sequence = 0
    try {
      while (!this.closed && !signal.aborted) {
        const { done, value } = await reader.read()
        if (done) break
        total += value.length
        if (total > 2 * 1024 * 1024) throw new ApiError(0, 'Event stream exceeded the supported size.')
        pending += decoder.decode(value, { stream: true })
        let boundary: number
        while ((boundary = pending.indexOf('\n\n')) >= 0) {
          const frame = pending.slice(0, boundary); if (frame.length > 16384) throw new ApiError(0, 'Event frame exceeded the supported size.'); pending = pending.slice(boundary + 2)
          const data = frame.split('\n').find(line => line.startsWith('data: '))
          const id = frame.split('\n').find(line => line.startsWith('id: '))?.slice(4)
          if (data) {
            const event = JSON.parse(data.slice(6)) as LiveEvent
            if (event.organization_id !== this.organization || event.job_id !== job || !Number.isSafeInteger(event.sequence) || event.sequence < 1 || !id || id.length > 2048 || /[\x00-\x1f\x7f]/.test(id)) throw new ApiError(0, 'Unexpected scoped event.')
            if (this.closed || signal.aborted) throw new DOMException('Organization changed', 'AbortError')
            if (event.sequence <= sequence) throw new ApiError(0, 'Event sequence did not advance.')
            sequence = event.sequence; last = id; onEvent(event, id)
          }
        }
        if (pending.length > 16384) throw new ApiError(0, 'Event frame exceeded the supported size.')
      }
    } finally { await reader.cancel(); reader.releaseLock() }
    return last
  }
}
