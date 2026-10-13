import { useEffect, useRef, useState } from 'react'
import { ApiError, ApiScope, errorMessage, sessionRequest } from './client'
import { validatedSession } from './session'
import type { Membership, Organization, Session } from './models'
import { Load, useResource, type Context } from './ui'
import { Dashboard, Wizard, Jobs, Contacts, Exports, Sources, UsageView, AuditView, SettingsView, type ContactFilters } from './views'
const screens = ['Dashboard', 'New extraction', 'Jobs', 'Contacts', 'Review queue', 'Exports', 'Sources', 'Usage', 'Audit', 'Settings'] as const
export type Screen = typeof screens[number]
export default function App() {
  const [session, setSession] = useState<Session>(), [error, setError] = useState<string>(), [loading, setLoading] = useState(true), [attempt, setAttempt] = useState(0), [selected, setSelected] = useState('')
  const [callback] = useState(() => typeof window === 'undefined' ? null : window.location.pathname === '/auth/complete' ? new URLSearchParams(window.location.search) : null)
  const complete = useRef(false)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(undefined)
    sessionRequest<unknown>('/auth/session', controller.signal).then(value => {
      const data = validatedSession(value)
      if (controller.signal.aborted) return
      setSession(data); setSelected(current => data.memberships.some(m => m.organization_id === current) ? current : data.memberships[0]?.organization_id ?? '')
    }).catch((failure: unknown) => { if (!controller.signal.aborted) { setSession(undefined); setSelected(''); setError(errorMessage(failure)) } }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [attempt])
  const expired = () => { setSession(undefined); setSelected(''); setError('Your session ended. Sign in again.') }
  const finishLogin = async () => {
    if (complete.current || !callback) return
    complete.current = true; setLoading(true)
    const state = callback.get('state'), code = callback.get('code')
    window.history.replaceState(null, '', '/')
    try {
      if (!state || state.length > 256 || !code || code.length > 4096) throw new ApiError(0, 'Invalid sign-in response. Start a new sign-in.')
      await sessionRequest('/auth/callback?' + new URLSearchParams({ state, code }))
      setAttempt(value => value + 1)
    } catch (failure) { setError(errorMessage(failure)); setLoading(false) }
  }
  return <><a className="skip" href="#main">Skip to workspace</a><header className="topbar"><div><p className="eyebrow">Academic contact research</p><h1>EmailMonitor</h1></div><span className="environment">Synthetic offline environment</span></header>
    <div className="environment-note" role="note">Authored fixtures only. No live acquisition, email sending, mailbox verification, external AI or production activation.</div>
    {!session ? <main id="main" className="signin"><h2>Operator workspace</h2>{loading && <p role="status">Checking the current session…</p>}{error && <p role="alert" className="error">{error}</p>}
      <p>Connect the documented synthetic service and its configured test identity provider. No demo contacts are inserted by this interface.</p>
      {callback && !complete.current && <button onClick={() => void finishLogin()}>Complete sign-in</button>}
      <a className="button" href="/api/v1/auth/start">Sign in with configured identity</a> <button onClick={() => setAttempt(v => v + 1)} disabled={loading}>Retry connection</button></main>
      : <><div className="sessionbar"><label>Active organization <select aria-label="Active organization" value={selected} onChange={event => { setSelected(event.target.value); setAttempt(v => v + 1) }}>
        {session.memberships.map((membership, index) => <option key={membership.organization_id} value={membership.organization_id}>Organization {index + 1} · {membership.organization_id.slice(0, 8)} · {membership.role}</option>)}</select></label><button onClick={async () => {
          try { const response = await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin', redirect: 'error', headers: { 'X-CSRF-Token': session.csrf_token } }); if (!response.ok) throw new ApiError(response.status, 'Sign-out could not be completed. Retry.'); expired() } catch (failure) { setError(errorMessage(failure)) }
        }}>Sign out</button></div>{error && <p role="alert">{error}</p>}
        {selected ? <OrganizationArea key={selected} membership={session.memberships.find(m => m.organization_id === selected)!} session={session} expired={expired} /> : <main id="main"><h2>No authorized organizations</h2><p>Ask the organization owner for membership. No tenant data is available.</p></main>}</>}
    <footer>First author, corresponding author, observed email, article-local identity, accepted association, technical checks and outreach eligibility remain separate.</footer></>
}
function OrganizationArea({ membership, session, expired }: { membership: Membership; session: Session; expired: () => void }) {
  const [scope, setScope] = useState<ApiScope>(), [screen, setScreen] = useState<Screen>('Dashboard'), [job, setJob] = useState<string>(), [revision, setRevision] = useState(0), [notice, setNotice] = useState(''), [busy, setBusy] = useState('')
  const [confirmation, setConfirmation] = useState<{ title: string; detail: string; work: () => Promise<unknown> }>()
  const dialog = useRef<HTMLDialogElement>(null)
  const expiredRef = useRef(expired); expiredRef.current = expired
  useEffect(() => { const active = new ApiScope(membership.organization_id, session.csrf_token, () => expiredRef.current()); setScope(active); return () => active.close() }, [membership.organization_id, session.csrf_token])
  useEffect(() => { if (confirmation) dialog.current?.showModal() }, [confirmation])
  if (!scope) return <main id="main"><p role="status">Opening current organization…</p></main>
  return <Workspace scope={scope} membership={membership} identity={session.identity_id} screen={screen} setScreen={setScreen} job={job} setJob={setJob} revision={revision} refresh={() => setRevision(v => v + 1)} notice={notice} setNotice={setNotice} busy={busy} setBusy={setBusy} confirm={setConfirmation}>
    <dialog ref={dialog} aria-labelledby="confirm-title" onClose={() => setConfirmation(undefined)} onCancel={() => setConfirmation(undefined)}><h2 id="confirm-title">{confirmation?.title}</h2><p>Active organization: {membership.organization_id}</p><p>{confirmation?.detail}</p><div className="actions"><button autoFocus onClick={() => dialog.current?.close()}>Keep unchanged</button><button className="danger" disabled={!!busy} onClick={async () => {
      if (!confirmation) return
      setBusy(confirmation.title)
      try { await confirmation.work(); if (!scope.closed) { setNotice('Action completed. Current permissions are rechecked by the server.'); setRevision(v => v + 1) } }
      catch (failure) { if (!scope.closed) setNotice(errorMessage(failure)) }
      finally { if (!scope.closed) { setBusy(''); dialog.current?.close() } }
    }}>Confirm {confirmation?.title.toLowerCase()}</button></div></dialog>
  </Workspace>
}
type WorkspaceProps = { scope: ApiScope; membership: Membership; identity: string; screen: Screen; setScreen: (screen: Screen) => void; job?: string; setJob: (id?: string) => void; revision: number; refresh: () => void; notice: string; setNotice: (value: string) => void; busy: string; setBusy: (value: string) => void; confirm: (value: { title: string; detail: string; work: () => Promise<unknown> }) => void; children: React.ReactNode }
function Workspace(props: WorkspaceProps) {
  const [filters, setFilters] = useState<Record<string, ContactFilters>>({
    contacts: { query: '', state: 'accepted', target: 'all', job: '' },
    review: { query: '', state: 'needs_review', target: 'all', job: '' },
  })
  const organization = useResource<Organization>(props.scope, '/', props.revision)
  // Organization detail is the base resource; scoped paths intentionally require a trailing slash.
  const context: Context = { scope: props.scope, revision: props.revision, refresh: props.refresh, identity: props.identity, zone: organization.data?.timezone ?? 'UTC', can: capability => props.membership.capabilities.includes(capability), openJob: id => { props.setJob(id); props.setScreen('Jobs') },
    confirm: (title, detail, work) => props.confirm({ title, detail, work }), act: async (label, work, success = 'Saved. Current organization data refreshed.') => {
      if (props.busy || props.scope.closed) return
      props.setBusy(label); props.setNotice('')
      try { await work(); if (!props.scope.closed) { props.setNotice(success); props.refresh() } }
      catch (failure) { if (!props.scope.closed) props.setNotice(errorMessage(failure)) }
      finally { if (!props.scope.closed) props.setBusy('') }
    } }
  return <div className="shell"><nav aria-label="Workspace">{screens.map(item => <button key={item} aria-current={item === props.screen ? 'page' : undefined} onClick={() => { props.setScreen(item); props.setNotice('') }}>{item}</button>)}</nav><main id="main" className="workspace" aria-busy={!!props.busy}><div className="workspace-heading"><div><p className="eyebrow">{props.membership.role.replaceAll('_', ' ')} · {props.scope.organization}</p><Load resource={organization}>{org => <h2>{org.display_name}</h2>}</Load><h3>{props.screen}</h3></div><button onClick={props.refresh}>Refresh current view</button></div>
    {props.busy && <p role="status">{props.busy}…</p>}{props.notice && <p role="status" className="notice">{props.notice}</p>}
    {props.screen === 'Dashboard' && <Dashboard context={context} navigate={props.setScreen} />}
    {props.screen === 'New extraction' && <Wizard context={context} />}
    {props.screen === 'Jobs' && <Jobs context={context} selected={props.job} select={props.setJob} />}
    {(props.screen === 'Contacts' || props.screen === 'Review queue') && <Contacts key={props.screen} context={context} review={props.screen === 'Review queue'} filters={filters[props.screen === 'Review queue' ? 'review' : 'contacts']} setFilters={value => setFilters(previous => ({ ...previous, [props.screen === 'Review queue' ? 'review' : 'contacts']: value }))} />}
    {props.screen === 'Exports' && <Exports context={context} />}
    {props.screen === 'Sources' && <Sources context={context} />}
    {props.screen === 'Usage' && <UsageView context={context} />}
    {props.screen === 'Audit' && <AuditView context={context} />}
    {props.screen === 'Settings' && <SettingsView context={context} organization={organization} />}
    {props.children}</main></div>
}
