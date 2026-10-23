import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiScope, errorMessage } from './client'
import type { RuntimeProfile } from './runtimeProfile'
import { scheduleSearch } from './search'
export type Resource<T> = { data?: T; loading: boolean; error?: string; stale?: boolean }
export function useResource<T>(scope: ApiScope, path: string | null, revision = 0): Resource<T> {
  const request = useMemo(() => ({ scope, path, revision }), [scope, path, revision])
  const [owned, setOwned] = useState<{ request: typeof request; resource: Resource<T> }>()
  useEffect(() => {
    const { scope, path } = request
    if (!path) return
    const controller = new AbortController()
    scope.request<T>(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted && !scope.closed) setOwned({ request, resource: { data, loading: false } })
    }).catch((error: unknown) => {
      if (controller.signal.aborted || scope.closed) return
      setOwned(current => ({ request, resource: { loading: false, error: errorMessage(error), stale: current?.request.scope === scope && current.request.path === path && current.resource.data !== undefined } }))
    })
    return () => controller.abort()
  }, [request])
  // A return to a previous path is a new request, including null/disabled intervals.
  // Memo eviction also starts a new request; its old result can never gain ownership.
  if (scope.closed || !path) return { loading: false }
  if (owned?.request !== request) return { loading: true }
  return owned.resource
}
export function useSettledSearch(scope: ApiScope, value: string): string | null {
  const [settled, setSettled] = useState({ scope, value })
  useEffect(() => scheduleSearch(value, scope.controller.signal, next => setSettled({ scope, value: next })), [scope, value])
  return !scope.closed && settled.scope === scope && settled.value === value ? value : null
}
export function Load<T>({ resource, children }: { resource: Resource<T>; children: (data: T) => ReactNode }) {
  return <>{resource.loading && <p role="status">Loading current organization data…</p>}
    {resource.error && <p role="alert" className="error">{resource.stale ? 'Stale view. ' : ''}{resource.error}</p>}
    {resource.data !== undefined && children(resource.data)}</>
}
export function Status({ value }: { value: string }) { return <span className={'status status-' + value.replace(/[^a-z_]/g, '')}>{value.replaceAll('_', ' ')}</span> }
export function Empty({ children = 'No records match the current scope.' }: { children?: ReactNode }) { return <p className="empty">{children}</p> }
export function Time({ value, zone = 'UTC' }: { value: string; zone?: string }) {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return <span>Unknown time</span>
  try { return <time dateTime={value}>{date.toLocaleString(undefined, { timeZone: zone })} ({zone})</time> }
  catch { return <time dateTime={value}>{date.toISOString()} (UTC fallback; unsupported configured timezone)</time> }
}
export const truth = (value: boolean | null) => value === true ? 'Observed' : value === false ? 'Not designated' : 'Unresolved'
export const uid = (value: string) => encodeURIComponent(value)
export type Action = (label: string, work: () => Promise<unknown>, success?: string) => Promise<void>
export type Confirm = (title: string, detail: string, work: () => Promise<unknown>) => void
export type Context = { runtimeProfile?: RuntimeProfile; scope: ApiScope; revision: number; refresh: () => void; act: Action; confirm: Confirm; can: (capability: string) => boolean; identity: string; zone: string; openJob: (id: string) => void; openJobContacts?: (id: string, review: boolean, item?: string) => void }
