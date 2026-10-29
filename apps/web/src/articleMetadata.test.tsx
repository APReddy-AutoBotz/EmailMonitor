import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ArticleMetadataPanel, type ArticleMetadata } from './articleMetadata'
import type { Resource } from './ui'
const data: ArticleMetadata = {
  view_version: 'article-metadata-v1', organization_id: 'org-a', batch_id: 'batch-a', source_url: 'https://synthetic.publisher.example/article-a.html', content_digest: 'a'.repeat(64), parser_version: 'synthetic-html-v1', observation_route: 'html',
  preferred_metadata: { title: 'Observed article', journal: 'Authored journal', publication_date: 'Spring 2026', doi: null },
  facts: [{ field: 'publication_date', value: 'Spring 2026', date_type: 'unspecified', evidence: { locator: 'article/time', excerpt: 'Spring 2026' } }, { field: 'journal', value: 'Another journal', date_type: 'unspecified', evidence: { locator: 'meta[1]', excerpt: 'Another journal' } }],
  fact_availability: 'recorded', multiple_value_fields: ['journal'], date_interpretation: 'retained_text_and_recorded_type_only',
}
const render = (resource: Resource<ArticleMetadata>, org = 'org-a', batch = 'batch-a') => renderToStaticMarkup(<ArticleMetadataPanel resource={resource} organization={org} batch={batch} />)
describe('current retained article metadata', () => {
  it('shows actual values, unknowns and all competing citations without inventing dates', () => {
    const html = render({ loading: false, data })
    for (const text of ['Authored journal', 'Another journal', 'Spring 2026', 'Unobserved', 'Recorded date type: Unspecified', 'Multiple retained values', 'article/time', 'no inferred calendar date']) expect(html).toContain(text)
    expect(html).not.toContain('2026-03-01')
    expect(html).toContain('<summary>Inspect all retained metadata values and citations</summary>')
  })
  it.each([{ data, loading: true }, { data, loading: false, stale: true }, { data, loading: false, error: 'revoked' }, { loading: false }])('does not retain prior values on unavailable reads', resource => {
    expect(render(resource)).not.toContain('Authored journal')
  })
  it.each([['org-b', 'batch-a'], ['org-a', 'batch-b']])('rejects mismatched response identity', (org, batch) => {
    expect(render({ loading: false, data }, org, batch)).not.toContain('Authored journal')
  })
  it('distinguishes unrecorded citations from a false empty-result claim', () => {
    const html = render({ loading: false, data: { ...data, fact_availability: 'not_recorded', facts: [], preferred_metadata: { title: null, journal: null, publication_date: null, doi: null }, multiple_value_fields: [] } })
    expect(html).toContain('Individual metadata citations were not recorded')
    expect(html).not.toContain('No metadata facts are retained')
  })
  it('renders untrusted retained text as text, not links or executable markup', () => {
    const html = render({ loading: false, data: { ...data, preferred_metadata: { ...data.preferred_metadata, title: '<script>fixture</script>' } } })
    expect(html).toContain('&lt;script&gt;fixture&lt;/script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href=')
  })
  it('preserves PDF citation page and coarse region precision', () => {
    const html = render({ loading: false, data: { ...data, observation_route: 'pdf', facts: [{ ...data.facts[0], evidence: { locator: 'page:1:fragment:1', excerpt: 'Date: Spring 2026', page: 1, region_precision: 'full_cropbox_not_glyph_bbox' } }] } })
    expect(html).toContain('PDF page 1')
    expect(html).toContain('full cropbox not glyph bbox')
  })
  it('ties a supplied date precision to its retained citation without claiming source support', () => {
    const html = render({ loading: false, data: { ...data, facts: [{ field: 'publication_date', value: '2024-02-29', date_type: 'published', evidence: { locator: 'article/time', excerpt: '2024-02-29' } }], date_precisions: [{ fact_index: 0, precision: 'day' }] } })
    expect(html).toContain('2024-02-29')
    expect(html).toContain('Retained text precision: day')
    expect(html).toContain('not source filter support')
    expect(html).toContain('do not establish a source-declared publication type')
  })
  it('keeps missing or duplicate precision annotations unavailable', () => {
    const repeated = [{ fact_index: 0, precision: 'day' as const }, { fact_index: 0, precision: 'month' as const }]
    expect(render({ loading: false, data: { ...data, date_precisions: repeated } })).toContain('Retained text precision: unavailable')
    expect(render({ loading: false, data })).toContain('Retained text precision: unavailable')
    const invalid = [{ fact_index: 0, precision: 'unexpected' }] as unknown as ArticleMetadata['date_precisions']
    expect(render({ loading: false, data: { ...data, date_precisions: invalid } })).toContain('Retained text precision: unavailable')
  })
})
