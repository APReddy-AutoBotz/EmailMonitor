import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import type { Outcome, Page } from './models'
import { CurrentObservationQuality } from './observationQuality'
import { Empty, Status, Time, useResource, type Context } from './ui'

// The caller keys this pager by organization and job. Each request owns its
// rendered rows and dialog, so a refresh cannot flash a previous response.
export function JobArticleOutcomes({ context: c, job, pulse = 0 }: { context: Context; job: string; pulse?: number }) {
  const [cursor, setCursor] = useState<string | null>(null)
  const [previous, setPrevious] = useState<(string | null)[]>([])
  const heading = useRef<HTMLHeadingElement>(null)
  const path = '/article-outcomes?' + new URLSearchParams({ job_id: job, ...(cursor ? { cursor } : {}), limit: '25' })
  return <section aria-label="Article outcomes">
    <h4 ref={heading} tabIndex={-1}>Article outcomes</h4>
    <p>Retained article results for this job, including no-contact, blocked and unsupported work. Each page contains at most 25 outcomes. Page counts are not whole-job totals.</p>
    <ArticleOutcomePage key={`${c.scope.organization}:${job}:${c.revision}:${pulse}:${cursor ?? ''}`} context={c} job={job} path={path} page={previous.length + 1} heading={heading}
      hasPrevious={previous.length > 0}
      back={() => { heading.current?.focus(); setCursor(previous[previous.length - 1]); setPrevious(previous.slice(0, -1)) }}
      next={next => { heading.current?.focus(); setPrevious([...previous, cursor]); setCursor(next) }} />
  </section>
}

function ArticleOutcomePage({ context: c, job, path, page, heading, hasPrevious, back, next }: {
  context: Context; job: string; path: string; page: number; heading: RefObject<HTMLHeadingElement | null>; hasPrevious: boolean; back: () => void; next: (cursor: string) => void
}) {
  const resource = useResource<Page<Outcome>>(c.scope, path)
  const [selected, setSelected] = useState<{ outcome: Outcome; opener: HTMLButtonElement }>()
  const pageContent = useRef<HTMLDivElement>(null)
  // Capture focus before React removes request-owned rows or controls. A stream
  // refresh must not strand keyboard users on body or move unrelated focus.
  useLayoutEffect(() => {
    const current = pageContent.current
    return () => {
      if (current?.contains(document.activeElement) && heading.current?.isConnected) heading.current.focus()
    }
  }, [heading])
  const data = resource.data
  const mismatched = data?.items.some(item => item.organization_id !== c.scope.organization || item.job_id !== job)
  const available = !c.scope.closed && !resource.loading && !resource.error && !resource.stale && !!data && !mismatched
  return <div ref={pageContent}>
    {!available ? <p role={resource.error ? 'alert' : 'status'}>{resource.loading && !c.scope.closed ? 'Loading current article outcomes…' : 'Current article outcomes are unavailable. Refresh before relying on this view.'}</p> : <>
      <p role="status">Page {page}: {data.items.length} article outcomes on this page.</p>
      {data.items.length ? <div className="tablewrap" tabIndex={0} aria-label="Scrollable article outcomes"><table>
        <caption>Current-authorized article outcomes</caption>
        <thead><tr><th>Source article</th><th>Outcome</th><th>Reason</th><th>Completed</th><th>Observation</th><th>Lineage</th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.item_id}>
          <td>{item.source_url}</td>
          <td><Status value={item.state} /></td>
          <td>{item.reason.replaceAll('_', ' ')}</td>
          <td>{item.completed_at ? <Time value={item.completed_at} zone={c.zone} /> : 'Completion time not recorded'}</td>
          <td>{item.observation_status ? <Status value={item.observation_status} /> : 'Observation status unavailable'}<br />
            {item.batch_id ? <button onClick={event => setSelected({ outcome: item, opener: event.currentTarget })}>Inspect article observation</button> : <span>No retained observation batch</span>}</td>
          <td>{item.inherited_job_id ? <>Inherited from job {item.inherited_job_id}</> : 'Not inherited'}</td>
        </tr>)}</tbody>
      </table></div> : <Empty>No retained article outcomes for this job.</Empty>}
    </>}
    <div className="actions">
      <button disabled={!hasPrevious || resource.loading || c.scope.closed} onClick={back}>Previous article outcome page</button>
      <button disabled={!available || !data?.next_cursor} onClick={() => { if (available && data?.next_cursor) next(data.next_cursor) }}>Next article outcome page</button>
    </div>
    {available && selected?.outcome.batch_id && <ArticleObservationDialog context={c} batch={selected.outcome.batch_id} opener={selected.opener} heading={heading} close={() => setSelected(undefined)} />}
  </div>
}

function ArticleObservationDialog({ context: c, batch, opener, heading, close }: {
  context: Context; batch: string; opener: HTMLButtonElement; heading: RefObject<HTMLHeadingElement | null>; close: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const current = dialog.current
    current?.showModal()
    return () => {
      current?.close()
      if (opener.isConnected) opener.focus()
      else if (heading.current?.isConnected) heading.current.focus()
    }
  }, [opener, heading])
  return <dialog ref={dialog} aria-labelledby="article-observation-title" onClose={close}>
    <button className="close" autoFocus onClick={() => dialog.current?.close()}>Close article observation</button>
    <h2 id="article-observation-title">Article observation details</h2>
    <p>Active organization: {c.scope.organization}</p>
    <p>This article-level view is available independently of contact candidates. It does not establish a complete extraction or an accepted author-email association.</p>
    <button onClick={() => setRevision(value => value + 1)}>Refresh article observation</button>
    <CurrentObservationQuality key={`${c.scope.organization}:${batch}:${c.revision}:${revision}`} scope={c.scope} batch={batch} />
  </dialog>
}
