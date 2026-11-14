import { useState, type FormEvent } from 'react'
import { ApiError, errorMessage, readBounded } from './client'
import { Empty, Status, type Context } from './ui'

/** Preview Open Access workspace: offline fixtures only, every row carries its evidence. */
export type OaSource = 'auto' | 'all' | 'europe-pmc' | 'openalex' | 'crossref' | 'biorxiv'
export type OaRoles = 'both' | 'corresponding' | 'first' | 'all'
export type OaPreset = 'instantly' | 'smartlead' | 'lemlist' | 'hubspot' | 'evidence' | 'researchers'
export type OaContact = {
  contact_id: string; source: string; doi: string | null; pmcid: string | null; article_title: string | null; journal: string | null
  publication_year: number | null; author_position: number | null; author_name: string | null; email: string
  is_first_author: boolean; is_corresponding_author: boolean; association_basis: string; association_status: string
  affiliations: string[]; orcid_id: string | null; orcid_status: string; evidence_locator: string; evidence_excerpt: string
  content_digest: string; full_text_url: string | null; technical_status: string; recency_level: string
  outreach_eligibility: 'eligible' | 'needs_review' | 'suppressed'; eligibility_reasons: string[]
}
export type OaArticle = {
  source: string; work_key: string; doi: string | null; pmcid: string | null; title: string | null; journal: string | null
  publication_year: number | null; status: string; reason: string | null; license_url: string | null; license_category: string; found_in: string[]
  authors_observed: number; candidates_observed: number; unmatched_candidates: number; contacts_retained: number
}
export type OaDiscovery = {
  query: string; source_used: string; route_reason: string; target_roles: OaRoles; reference_year: number
  total_articles_scanned: number; articles_with_full_text: number; articles: OaArticle[]; contacts_extracted: OaContact[]
  corresponding_authors_count: number; first_authors_count: number; unmatched_candidates_count: number
  eligible_contacts_count: number; hit_count_reported: number | null; source_errors: Record<string, string>
}
export type OaDocument = {
  kind: 'pdf' | 'jats_xml' | 'html'; parser_version: string; content_digest: string; status: string; reason: string | null
  title: string | null; journal: string | null; doi: string | null; publication_year: number | null; authors: string[]
  contacts: OaContact[]; candidates_observed: number; unmatched_candidates: number; review_notes: string[]; linked_pdf_url: string | null
}
export type OaResearcher = {
  researcher_key: string; display_names: string[]; emails: string[]; orcids: string[]; publication_count: number
  corresponding_count: number; first_author_count: number; latest_publication_year: number | null; latest_affiliation: string | null
  affiliation_changed: boolean; activity: string; outreach_eligibility: string; review_flags: string[]
}
export type OaForm = {
  query: string; source: OaSource; roles: OaRoles; maxResults: number; fromYear: string; untilYear: string
  excludeJournals: string; suppressedEmails: string; suppressedDomains: string
}
export const defaultForm: OaForm = { query: '', source: 'auto', roles: 'both', maxResults: 25, fromYear: '', untilYear: '', excludeJournals: '', suppressedEmails: '', suppressedDomains: '' }
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024
const MAX_EXPORT_BYTES = 50 * 1024 * 1024

export function splitList(value: string, limit: number): string[] {
  const items = value.split(/[\n,;]+/).map(item => item.trim()).filter(Boolean)
  return [...new Set(items)].slice(0, limit)
}

function year(value: string, label: string): number | null {
  if (!value.trim()) return null
  if (!/^\d{4}$/.test(value.trim())) throw new ApiError(0, label + ' must be a four-digit year.')
  const parsed = Number(value)
  if (parsed < 1800 || parsed > 2100) throw new ApiError(0, label + ' must be between 1800 and 2100.')
  return parsed
}

/** Client-side bounds mirror the server; the server remains authoritative. */
export function discoverBody(form: OaForm): Record<string, unknown> {
  const query = form.query.trim()
  if (!query) throw new ApiError(0, 'Enter a keyword, DOI or PMCID.')
  if (query.length > 1000 || /[\x00-\x1f\x7f]/.test(query)) throw new ApiError(0, 'The query is too long or contains control characters.')
  if (!Number.isInteger(form.maxResults) || form.maxResults < 1 || form.maxResults > 100) throw new ApiError(0, 'Maximum articles must be between 1 and 100.')
  const from = year(form.fromYear, 'From year'), until = year(form.untilYear, 'Until year')
  if (from !== null && until !== null && from > until) throw new ApiError(0, 'From year must not be after until year.')
  return {
    query, source: form.source, max_results: form.maxResults, target_roles: form.roles, from_year: from, until_year: until,
    exclude_journals: splitList(form.excludeJournals, 50), suppressed_emails: splitList(form.suppressedEmails, 10000),
    suppressed_domains: splitList(form.suppressedDomains, 1000),
  }
}

export function documentQuery(knownAuthors: string, pageUrl: string, roles: OaRoles): string {
  const params = new URLSearchParams({ target_roles: roles })
  const authors = splitList(knownAuthors, 100)
  if (authors.length) params.set('known_authors', authors.join('; '))
  const url = pageUrl.trim()
  if (url) {
    if (!/^https:\/\/[^\s]+$/.test(url) || url.length > 2048) throw new ApiError(0, 'The page address must be an https:// URL.')
    params.set('page_url', url)
  }
  return '?' + params.toString()
}

export const basisLabel = (basis: string): string => ({
  contrib_email: 'Address inside the author entry',
  corresp_xref: 'Correspondence note linked to this author',
  corresp_initials: 'Shared note, matched by initials',
  corresp_name_proximity: 'Shared note, matched by surname',
  sole_corresponding_author: 'Only corresponding author in the article',
  highwire_author_sequence: 'Page metadata, author sequence',
  correspondence_block_surname: 'Page correspondence block, matched by surname',
  pdf_correspondence_surname: 'PDF correspondence line, matched by surname',
  unmatched: 'Not linked to an author',
} as Record<string, string>)[basis] ?? basis.replaceAll('_', ' ')

export const outcomeLabel = (status: string): string => ({
  contacts_observed: 'Addresses observed', no_contact: 'Full text read, no address', full_text_unavailable: 'Own full text unavailable',
  excluded_by_filter: 'Excluded by filter', failed: 'Failed safely',
} as Record<string, string>)[status] ?? status.replaceAll('_', ' ')

const role = (c: OaContact) => c.author_name === null ? 'Unlinked' : [c.is_first_author && 'First', c.is_corresponding_author && 'Corresponding'].filter(Boolean).join(' + ') || 'Other author'

async function download(context: Context, path: string, init: RequestInit, filename: string): Promise<string> {
  const response = await context.scope.response(path, init)
  const written = response.headers.get('x-emailmonitor-rows-written') ?? '?'
  const withheld = response.headers.get('x-emailmonitor-rows-withheld-unsafe') ?? '0'
  const bytes = await readBounded(response, MAX_EXPORT_BYTES)
  const object = URL.createObjectURL(new Blob([bytes as BlobPart], { type: 'text/csv' }))
  try { const link = document.createElement('a'); link.href = object; link.download = filename; link.click() }
  finally { setTimeout(() => URL.revokeObjectURL(object), 0) }
  return `${written} row(s) exported` + (withheld !== '0' ? `; ${withheld} withheld because a cell was formula-unsafe` : '') + '.'
}

function ContactTable({ contacts, caption }: { contacts: OaContact[]; caption: string }) {
  const [open, setOpen] = useState<string>()
  if (!contacts.length) return <Empty>No addresses for the selected roles. Unlinked or unavailable articles are listed with their outcomes.</Empty>
  return <div className="tablewrap" tabIndex={0}><table className="oa-contacts"><caption>{caption}</caption>
    <thead><tr><th>Address</th><th>Author and role</th><th>Article</th><th>Link basis</th><th>Export readiness</th><th>Evidence</th></tr></thead>
    <tbody>{contacts.map(c => <tr key={c.contact_id}>
      <td><code>{c.email}</code><br /><small>{c.technical_status === 'syntax_valid_not_mailbox_verified' ? 'Syntax valid · mailbox not verified' : 'Syntax invalid'}</small></td>
      <td>{c.author_name ?? <em>No author link</em>}<br /><small>{role(c)}{c.orcid_id ? ' · ORCID ' + c.orcid_id : ''}</small>{c.affiliations[0] && <><br /><small>{c.affiliations[0]}</small></>}</td>
      <td>{c.article_title ?? <em>Untitled</em>}<br /><small>{[c.journal, c.publication_year ?? 'year unknown', c.doi && 'doi:' + c.doi].filter(Boolean).join(' · ')}</small></td>
      <td>{basisLabel(c.association_basis)}<br /><Status value={c.association_status} /></td>
      <td><Status value={c.outreach_eligibility} />{c.eligibility_reasons.length > 0 && <><br /><small>{c.eligibility_reasons.map(r => r.replaceAll('_', ' ')).join(', ')}</small></>}</td>
      <td><button aria-expanded={open === c.contact_id} onClick={() => setOpen(open === c.contact_id ? undefined : c.contact_id)}>{open === c.contact_id ? 'Hide' : 'Show'}</button>
        {open === c.contact_id && <div className="oa-evidence"><blockquote>{c.evidence_excerpt}</blockquote><p><small>Locator <code>{c.evidence_locator}</code></small></p><p><small>Document SHA-256 <code>{c.content_digest.slice(0, 16)}…</code></small></p>{c.full_text_url && <p><small>Source {c.full_text_url}</small></p>}</div>}</td>
    </tr>)}</tbody></table></div>
}

function Summary({ result }: { result: OaDiscovery }) {
  const items: [string, number | string][] = [['Articles scanned', result.total_articles_scanned], ['Own full text read', result.articles_with_full_text], ['Addresses (selected roles)', result.contacts_extracted.length], ['Export-ready', result.eligible_contacts_count], ['Unlinked addresses', result.unmatched_candidates_count]]
  return <div className="oa-summary" role="group" aria-label="Discovery summary">{items.map(([label, value]) => <div key={label} className="oa-stat"><span>{label}</span><strong>{value}</strong></div>)}
    {Object.entries(result.source_errors).map(([name, reason]) => <p key={name} role="alert" className="error">{name} could not be searched ({reason.replaceAll('_', ' ')}); other sources still ran.</p>)}
    <p className="oa-route">Source <strong>{result.source_used}</strong> ({result.route_reason.replaceAll('_', ' ')}){result.hit_count_reported !== null ? ` · source reported ${result.hit_count_reported} matching record(s)` : ''}</p></div>
}

function Outcomes({ articles }: { articles: OaArticle[] }) {
  if (!articles.length) return <Empty>No works matched this query in the offline fixtures.</Empty>
  return <div className="tablewrap" tabIndex={0}><table><caption>Every discovered work and what happened to it</caption><thead><tr><th>Work</th><th>Outcome</th><th>Authors / addresses</th></tr></thead>
    <tbody>{articles.map(a => <tr key={a.source + a.work_key}><td>{a.title ?? a.work_key}<br /><small>{[a.journal, a.publication_year, a.pmcid, a.doi && 'doi:' + a.doi].filter(Boolean).join(' · ')}</small></td>
      <td><Status value={a.status} /> {outcomeLabel(a.status)}{a.reason && <><br /><small>{a.reason.replaceAll('_', ' ')}</small></>}<br /><small>Found in {a.found_in.join(', ')} · license {a.license_category}</small></td>
      <td>{a.authors_observed} authors · {a.candidates_observed} addresses · {a.unmatched_candidates} unlinked · {a.contacts_retained} shown</td></tr>)}</tbody></table></div>
}

export function OpenAccessWorkspace({ context }: { context: Context }) {
  const [tab, setTab] = useState<'search' | 'document' | 'researchers'>('search')
  const [form, setForm] = useState<OaForm>(defaultForm)
  const [result, setResult] = useState<OaDiscovery>()
  const [researchers, setResearchers] = useState<OaResearcher[]>()
  const [doc, setDoc] = useState<OaDocument>()
  const [file, setFile] = useState<File>()
  const [knownAuthors, setKnownAuthors] = useState(''), [pageUrl, setPageUrl] = useState(''), [docRoles, setDocRoles] = useState<OaRoles>('all')
  const [preset, setPreset] = useState<OaPreset>('instantly')
  const [message, setMessage] = useState<string>(), [failure, setFailure] = useState<string>(), [busy, setBusy] = useState(false)
  const canExport = context.can('results.export'), canSearch = context.can('source.acquire')
  const update = <K extends keyof OaForm>(key: K, value: OaForm[K]) => setForm(previous => ({ ...previous, [key]: value }))
  const run = async (work: () => Promise<void>) => {
    if (busy || context.scope.closed) return
    setBusy(true); setFailure(undefined); setMessage(undefined)
    try { await work() } catch (error) { if (!context.scope.closed) setFailure(errorMessage(error)) } finally { if (!context.scope.closed) setBusy(false) }
  }
  const search = (event: FormEvent) => { event.preventDefault(); void run(async () => { const body = discoverBody(form); setResult(await context.scope.write<OaDiscovery>('/open-access/discover', body)); setResearchers(undefined) }) }
  const loadResearchers = () => void run(async () => { const body = discoverBody(form); const data = await context.scope.write<{ researchers: OaResearcher[] }>('/open-access/researchers', { ...body, target_roles: 'all' }); setResearchers(data.researchers) })
  const exportFile = () => void run(async () => { const body = discoverBody(form); setMessage(await download(context, '/open-access/export', { method: 'POST', body: JSON.stringify({ ...body, preset }) }, `emailmonitor-${preset}-export.csv`)) })
  const analyze = (event: FormEvent) => { event.preventDefault(); void run(async () => {
    if (!file) throw new ApiError(0, 'Choose a PDF, JATS XML or saved article page.')
    if (file.size > MAX_UPLOAD_BYTES) throw new ApiError(0, 'Documents are limited to 20 MB.')
    const bytes = await file.arrayBuffer()
    const type = file.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : file.name.toLowerCase().endsWith('.xml') ? 'application/xml' : 'text/html'
    setDoc(await context.scope.request<OaDocument>('/open-access/documents' + documentQuery(knownAuthors, pageUrl, docRoles), { method: 'POST', body: bytes, headers: { 'Content-Type': type } }))
  }) }

  return <section className="oa" aria-labelledby="oa-title">
    <h4 id="oa-title">Open Access contact discovery</h4>
    <p className="field-hint">Offline preview over committed synthetic fixtures. Every address is copied from its own article&apos;s full text with a document hash and excerpt; nothing is guessed, verified as a live mailbox, or sent.</p>
    <div className="oa-tabs" role="tablist">{([['search', 'Search open access'], ['document', 'Analyze a document'], ['researchers', 'Researchers']] as const).map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{label}</button>)}</div>
    {busy && <p role="status">Working…</p>}{failure && <p role="alert" className="error">{failure}</p>}{message && <p role="status" className="notice">{message}</p>}
    {tab !== 'document' && <form onSubmit={search} className="oa-form" aria-label="Open access search">
      <div className="formgrid">
        <label>Keyword, DOI or PMCID<input required maxLength={1000} value={form.query} placeholder="e.g. CRISPR base editing · 10.1038/… · PMC10293847" onChange={e => update('query', e.target.value)} /></label>
        <label>Source<select value={form.source} onChange={e => update('source', e.target.value as OaSource)}><option value="auto">Automatic (identifier-aware)</option><option value="all">All sources, merged (Europe PMC + OpenAlex + Crossref)</option><option value="europe-pmc">Europe PMC full text</option><option value="openalex">OpenAlex</option><option value="crossref">Crossref</option><option value="biorxiv">bioRxiv preprints</option></select></label>
        <label>Authors<select value={form.roles} onChange={e => update('roles', e.target.value as OaRoles)}><option value="both">First or corresponding</option><option value="corresponding">Corresponding only</option><option value="first">First only</option><option value="all">All observed, including unlinked</option></select></label>
        <label>Maximum articles<input type="number" min={1} max={100} value={form.maxResults} onChange={e => update('maxResults', Number(e.target.value))} /></label>
        <label>From year<input inputMode="numeric" maxLength={4} value={form.fromYear} onChange={e => update('fromYear', e.target.value)} /></label>
        <label>Until year<input inputMode="numeric" maxLength={4} value={form.untilYear} onChange={e => update('untilYear', e.target.value)} /></label>
      </div>
      <details className="governance-disclosure"><summary><span className="disclosure-title">Exclusions and suppression</span><span className="disclosure-badge">Applied before export</span></summary>
        <div className="formgrid"><label>Exclude journals (one per line)<textarea rows={3} value={form.excludeJournals} onChange={e => update('excludeJournals', e.target.value)} /></label>
          <label>Suppressed addresses<textarea rows={3} value={form.suppressedEmails} onChange={e => update('suppressedEmails', e.target.value)} /></label>
          <label>Suppressed domains (subdomains included)<textarea rows={3} value={form.suppressedDomains} onChange={e => update('suppressedDomains', e.target.value)} /></label></div></details>
      <div className="actions"><button type="submit" disabled={busy || !canSearch}>Search fixtures</button>
        {tab === 'researchers' && <button type="button" disabled={busy || !canSearch} onClick={loadResearchers}>Build researcher list</button>}
        <label className="inline">Export as<select value={preset} onChange={e => setPreset(e.target.value as OaPreset)}><option value="instantly">Instantly</option><option value="smartlead">Smartlead</option><option value="lemlist">Lemlist</option><option value="hubspot">HubSpot</option><option value="evidence">Evidence audit (all reviewable rows)</option><option value="researchers">Researchers (one row each)</option></select></label>
        <button type="button" disabled={busy || !canExport || !canSearch} onClick={exportFile}>Download CSV</button></div>
      {!canSearch && <p className="field-hint">Your role cannot run source discovery.</p>}
      {!canExport && <p className="field-hint">Your role cannot export results.</p>}
    </form>}
    {tab === 'search' && result && <><Summary result={result} /><Outcomes articles={result.articles} /><ContactTable contacts={result.contacts_extracted} caption={`Addresses for “${result.query}”`} /></>}
    {tab === 'researchers' && researchers && (researchers.length ? <div className="tablewrap" tabIndex={0}><table><caption>Researchers (addresses grouped; names never merge people)</caption><thead><tr><th>Researcher</th><th>Addresses</th><th>Activity</th><th>Papers</th><th>Readiness</th></tr></thead>
      <tbody>{researchers.map(r => <tr key={r.researcher_key}><td>{r.display_names.join(' / ') || <em>No author link</em>}{r.orcids.length > 0 && <><br /><small>ORCID {r.orcids.join(', ')}</small></>}{r.latest_affiliation && <><br /><small>{r.latest_affiliation}{r.affiliation_changed ? ' (affiliation changed)' : ''}</small></>}</td>
        <td>{r.emails.map(e => <div key={e}><code>{e}</code></div>)}</td><td><Status value={r.activity} /><br /><small>latest {r.latest_publication_year ?? 'unknown'}</small></td>
        <td>{r.publication_count} total · {r.corresponding_count} corresponding · {r.first_author_count} first</td>
        <td><Status value={r.outreach_eligibility} />{r.review_flags.length > 0 && <><br /><small>{r.review_flags.map(f => f.replaceAll('_', ' ')).join(', ')}</small></>}</td></tr>)}</tbody></table></div> : <Empty>No researchers for this query.</Empty>)}
    {tab === 'document' && <form onSubmit={analyze} className="oa-form" aria-label="Analyze a document">
      <p className="field-hint">Use a PDF, JATS XML or saved article page that you are permitted to read. It is parsed once and not stored; links inside it are reported, never opened.</p>
      <div className="formgrid"><label>Document<input type="file" accept=".pdf,.xml,.html,.htm,application/pdf,text/html,application/xml" onChange={e => setFile(e.target.files?.[0])} /></label>
        <label>Known author names (for PDFs; one per line, in order)<textarea rows={3} value={knownAuthors} onChange={e => setKnownAuthors(e.target.value)} /></label>
        <label>Page address (optional, provenance only)<input type="url" maxLength={2048} value={pageUrl} onChange={e => setPageUrl(e.target.value)} /></label>
        <label>Authors<select value={docRoles} onChange={e => setDocRoles(e.target.value as OaRoles)}><option value="all">All observed, including unlinked</option><option value="both">First or corresponding</option><option value="corresponding">Corresponding only</option></select></label></div>
      <div className="actions"><button type="submit" disabled={busy || !file || !canSearch}>Extract contacts</button></div>
      {doc && <><div className="oa-summary" role="group" aria-label="Document summary"><div className="oa-stat"><span>Type</span><strong>{doc.kind.replace('_', ' ')}</strong></div><div className="oa-stat"><span>Status</span><strong>{doc.status.replaceAll('_', ' ')}</strong></div><div className="oa-stat"><span>Addresses observed</span><strong>{doc.candidates_observed}</strong></div><div className="oa-stat"><span>Unlinked</span><strong>{doc.unmatched_candidates}</strong></div>
        <p className="oa-route">{doc.title ?? 'Untitled document'}{doc.doi ? ' · doi:' + doc.doi : ''}{doc.authors.length ? ' · ' + doc.authors.join(', ') : ''}</p></div>
        {doc.review_notes.map(note => <p key={note} className="field-hint">Review note: {note}</p>)}
        {doc.linked_pdf_url && <p className="field-hint">The page links an article PDF ({doc.linked_pdf_url}); it was not opened.</p>}
        <ContactTable contacts={doc.contacts} caption="Addresses observed in this document" /></>}
    </form>}
  </section>
}
