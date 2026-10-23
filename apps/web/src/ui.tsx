import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError, ApiScope, errorMessage } from './client'
import type { RuntimeProfile } from './runtimeProfile'
import { scheduleSearch } from './search'
export type Resource<T> = { data?: T; loading: boolean; error?: string; stale?: boolean }
export function useResource<T>(scope: ApiScope, path: string | null, revision = 0): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ loading: true })
  const lastPath = useRef<string | null>(null)
  useEffect(() => {
    if (!path) { setState({ loading: false }); return }
    const controller = new AbortController()
    const changed = lastPath.current !== path
    lastPath.current = path
    setState(previous => changed ? { loading: true } : { ...previous, loading: true, error: undefined })
    scope.request<T>(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted && !scope.closed) setState({ data, loading: false })
    }).catch((error: unknown) => {
      if (controller.signal.aborted || scope.closed) return
      setState(previous => ({ loading: false, error: errorMessage(error),
        data: error instanceof ApiError && [401, 403, 404].includes(error.status) ? undefined : previous.data,
        stale: !(error instanceof ApiError && [401, 403, 404].includes(error.status)) && previous.data !== undefined }))
    })
    return () => controller.abort()
  }, [scope, path, revision])
  return state
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
export type Context = { runtimeProfile?: RuntimeProfile; scope: ApiScope; revision: number; refresh: () => void; act: Action; confirm: Confirm; can: (capability: string) => boolean; identity: string; zone: string; openJob: (id: string) => void; openJobContacts?: (id: string, review: boolean) => void }
