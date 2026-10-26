import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { JobTimingPanel, type JobTiming } from './jobTiming'
import type { Progress } from './models'
import type { Resource } from './ui'
const data: JobTiming = { view_version: 'job-timing-v1', organization_id: 'org-a', job_id: 'job-a', revision: 5, generation: 2, state: 'completed', basis: 'first_queued_to_current_terminal_event', availability: 'recorded', queued_at: '2026-01-01T00:00:00Z', terminal_at: '2026-01-01T00:00:12.5Z', elapsed_seconds: 12.5, includes_waiting_and_pauses: true }
const progress: Progress = { organization_id: 'org-a', job_id: 'job-a', revision: 5, generation: 2, state: 'completed', discovery_pages: 1, source_reported_total: null, unique_articles: 1, duplicates: 0, discovery_complete: true, completeness: 'single_article', discovery_stop_reason: 'single_article', counts: { discovered: 1, pending: 0, active: 0, retry_wait: 0, terminal: 1, by_outcome: {} }, accepted_associations: 0, review_needed_associations: 0, progress_percent: 100, last_sequence: 4 }
const render = (resource: Resource<JobTiming>, current: Resource<Progress> = { loading: false, data: progress }) => renderToStaticMarkup(<JobTimingPanel resource={resource} organization="org-a" job="job-a" progress={current} zone="UTC" />)
describe('recorded queue-to-terminal interval', () => {
  it('labels elapsed time and its limits with explicit-zone timestamps', () => {
    const html = render({ loading: false, data })
    expect(html).toContain('12.500')
    expect(html).toContain('includes waiting and pauses')
    expect(html).toContain('not worker CPU time')
    expect(html).toContain('UTC')
  })
  it.each([{ loading: true, data }, { loading: false, data, stale: true }, { loading: false, data, error: 'refused' }, { loading: false }])('hides stale unavailable timing', resource => {
    expect(render(resource)).not.toContain('12.500')
  })
  it.each([{ organization_id: 'org-b' }, { job_id: 'job-b' }, { revision: 6 }, { generation: 3 }, { state: 'paused' }])('hides mismatched job scope and revision', change => {
    expect(render({ loading: false, data: { ...data, ...change } })).not.toContain('12.500')
  })
  it('hides timing while current progress is stale', () => {
    expect(render({ loading: false, data }, { loading: false, data: progress, stale: true })).not.toContain('12.500')
  })
  it.each(['not_started', 'not_terminal', 'not_recorded', 'inconsistent'] as const)('keeps %s unknown', availability => {
    const html = render({ loading: false, data: { ...data, availability, elapsed_seconds: null, queued_at: null, terminal_at: null } })
    expect(html).not.toContain('12.500')
    expect(html).not.toContain('<dd>0')
  })
})
