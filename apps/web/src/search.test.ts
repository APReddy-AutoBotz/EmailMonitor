import { afterEach, describe, expect, it, vi } from 'vitest'
import { scheduleSearch, SEARCH_SETTLE_MS } from './search'
afterEach(() => vi.useRealTimers())
describe('bounded current-scope keyboard search', () => {
  it.each(['no-such-observed-person', '10.9999/synthetic.article-a'])('applies only the final unchanged selector after a rapid keyboard burst: %s', text => {
    vi.useFakeTimers()
    const controller = new AbortController(), apply = vi.fn()
    let cancel = () => {}
    for (let index = 1; index <= text.length; index++) { cancel(); cancel = scheduleSearch(text.slice(0, index), controller.signal, apply); vi.advanceTimersByTime(5) }
    expect(apply).not.toHaveBeenCalled()
    vi.advanceTimersByTime(SEARCH_SETTLE_MS)
    expect(apply).toHaveBeenCalledExactlyOnceWith(text)
    cancel()
  })
  it('cancels old-tenant scheduled work while allowing the new scope', () => {
    vi.useFakeTimers()
    const old = new AbortController(), current = new AbortController(), apply = vi.fn()
    scheduleSearch('old tenant', old.signal, apply); old.abort()
    scheduleSearch('current tenant', current.signal, apply)
    vi.advanceTimersByTime(SEARCH_SETTLE_MS)
    expect(apply).toHaveBeenCalledExactlyOnceWith('current tenant')
  })
  it('does not run after unmount cleanup or an already closed scope', () => {
    vi.useFakeTimers()
    const controller = new AbortController(), apply = vi.fn()
    scheduleSearch('unmounted', controller.signal, apply)()
    controller.abort(); scheduleSearch('closed', controller.signal, apply)
    vi.runAllTimers()
    expect(apply).not.toHaveBeenCalled()
  })
})
