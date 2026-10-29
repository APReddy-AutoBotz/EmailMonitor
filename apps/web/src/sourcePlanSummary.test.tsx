import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Job } from './models'
import { launchableSourcePlan, SourcePlanSummary } from './sourcePlanSummary'

const job: Job = {
  id: 'job', kind: 'extraction', state: 'draft', row_version: 1, generation: 1, created_at: '', discovery_complete: false,
  request: { input: { type: 'keyword', source_id: 'synthetic-publisher' }, options: { max_articles: 50, max_search_pages: 2, author_target: 'both', allow_pdf: false, allow_browser: true } },
}
const render = (plan: Record<string, unknown>, current: Job = job) => renderToStaticMarkup(<SourcePlanSummary plan={plan} job={current} />)

describe('readable source preflight', () => {
  it('allows only recognized persisted classifications and does not coerce malformed values', () => {
    expect(launchableSourcePlan({ plan: { classification: 'article' } })).toBe(true)
    expect(launchableSourcePlan({ classification: 'search_results' })).toBe(true)
    expect(launchableSourcePlan({ plan: { classification: 'article' }, persisted: false })).toBe(false)
    expect(launchableSourcePlan({ plan: { classification: ['article'] } })).toBe(false)
    expect(launchableSourcePlan({ plan: null, classification: 'article' })).toBe(false)
    expect(launchableSourcePlan({ plan: { classification: 'future' } })).toBe(false)
  })
  it('distinguishes the requested limit from the server cap and describes authority as current', () => {
    const html = render({ source_id: 'synthetic-publisher', max_pages: 2, max_articles: 12, policy_version: 3, checkpoint: { reported_total: 90, articles: ['https://synthetic.publisher.example/article-a.html'] }, plan: { classification: 'search_results', reason: 'supported_fixture', start_url: 'https://synthetic.publisher.example/search-page-1.html', original_query: 'Original', effective_query: 'Corrected' } })
    expect(html).toContain('Search results.')
    expect(html).toContain('<dt>Requested article limit</dt><dd>50</dd>')
    expect(html).toContain('<dt>Effective article cap</dt><dd>12</dd>')
    expect(html).toContain('<dt>Maximum result pages</dt><dd>2</dd>')
    expect(html).toContain('<dt>Planned start URL</dt><dd>https://synthetic.publisher.example/search-page-1.html</dd>')
    expect(html).toContain('<dt>Source-reported total at planning</dt><dd>90</dd>')
    expect(html).toContain('<dt>Article URLs listed at planning</dt><dd>1</dd>')
    expect(html).toContain('Listed URLs are not verified completed articles')
    expect(html).toContain('<dt>Original query</dt><dd>Original</dd>')
    expect(html).toContain('<dt>Effective query</dt><dd>Corrected</dd>')
    expect(html).toContain('<dt>Browser work</dt><dd>Requested</dd>')
    expect(html).toContain('<dt>Authored PDF fixtures</dt><dd>Not requested</dd>')
    expect(html).toContain('not permission to acquire')
    expect(html).toContain('Estimated units and cost are unavailable')
    expect(html).toContain('<summary>Technical plan details</summary>')
  })
  it('explains a refused filter and preserves explicit date type without claiming it was applied', () => {
    const current = { ...job, request: { ...job.request, filters: { publication_date_type: 'online', publication_from: '2026-01-15' } } }
    const html = render({ plan: { classification: 'unsupported', reason: 'fixture_filters_unavailable' }, persisted: false }, current)
    expect(html).toContain('Unsupported.')
    expect(html).toContain('cannot apply the requested filters')
    expect(html).toContain('The server did not persist this plan. It cannot be launched')
    expect(html).toContain('online; from 2026-01-15 to Unavailable')
    expect(html).toContain('not proof that the source applied the filter')
    expect(html).toContain('<dt>Effective article cap</dt><dd>Unavailable</dd>')
  })
  it('explains unavailable reuse without implying fresh acquisition or eligibility', () => {
    const current = { ...job, request: { ...job.request, reuse: { mode: 'verified_retained', fresh_since: '2026-01-01T00:00:00Z' } } }
    const html = render({ plan: { classification: 'unsupported', reason: 'retained_reuse_unavailable' } }, current)
    expect(html).toContain('Fresh acquisition was not substituted')
    expect(html).toContain('verified_retained; fresh since 2026-01-01T00:00:00Z')
    expect(html).toContain('Eligibility is checked by the server')
  })
  it('does not infer an unknown source, cap, option, classification or reason', () => {
    const html = render({ classification: 'future_classification', reason: 'future_reason', max_articles: '12' }, { ...job, request: undefined })
    expect(html).toContain('<strong>Unavailable.</strong>')
    expect(html).toContain('did not provide a recognized explanation')
    expect(html).toContain('<dt>Source identity</dt><dd>Unavailable</dd>')
    expect(html).toContain('<dt>Effective article cap</dt><dd>Unavailable</dd>')
    expect(html).toContain('<dt>Browser work</dt><dd>Unavailable</dd>')
    expect(html).toContain('<dt>Source-reported total at planning</dt><dd>Unavailable</dd>')
    expect(html).toContain('<dt>Article URLs listed at planning</dt><dd>Unavailable</dd>')
  })
  it('escapes query content rather than rendering it as markup', () => {
    const html = render({ plan: { classification: 'needs_refinement', reason: 'fixture_topic_unavailable', original_query: '<script>test</script>' } })
    expect(html).toContain('&lt;script&gt;test&lt;/script&gt;')
    expect(html).not.toContain('<script>test</script>')
  })
})
