/** Coalesce keyboard search bursts without carrying work across tenant cancellation. */
export const SEARCH_SETTLE_MS = 250
export function scheduleSearch(value: string, signal: AbortSignal, apply: (value: string) => void): () => void {
  let closed = false
  const cancel = () => { closed = true; clearTimeout(timer); signal.removeEventListener('abort', cancel) }
  const timer = setTimeout(() => { if (!closed && !signal.aborted) apply(value); signal.removeEventListener('abort', cancel) }, SEARCH_SETTLE_MS)
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) cancel()
  return cancel
}
