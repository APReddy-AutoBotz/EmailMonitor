import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ObservationQualityPanel } from './observationQuality'
import type { ObservationQuality } from './models'
import type { Resource } from './ui'
const data: ObservationQuality = {
  view_version: 'observation-quality-v1', organization_id: 'org-a', batch_id: 'batch-a',
  scope: 'article', parser_version: 'elsevier-xml-head-v1', observation_route: 'article_xml',
  observation_status: 'partial', reason_availability: 'recorded', reasons: ['unsupported_affiliation'],
  review_scope: 'author_email_association',
}
const render = (resource: Resource<ObservationQuality>, organization = 'org-a', batch = 'batch-a') => renderToStaticMarkup(<ObservationQualityPanel resource={resource} organization={organization} batch={batch} />)
describe('retained article quality review boundary', () => {
  it('describes article uncertainty without author attribution or review repair', () => {
    const html = render({ data, loading: false })
    expect(html).toContain('Retained parser outcome: partial')
    expect(html).toContain('does not identify which author')
    expect(html).toContain('Missing affiliations remain unobserved, not confirmed absent')
    expect(html).toContain('does not resolve affiliation uncertainty')
  })
  it.each([
    { data, loading: true }, { data, loading: false, stale: true },
    { data, loading: false, error: 'revoked' }, { loading: false },
  ])('hides previous successful quality on unavailable reads', resource => {
    expect(render(resource)).not.toContain('Retained parser outcome: partial')
  })
  it.each([['org-b', 'batch-a'], ['org-a', 'batch-b']])('rejects mismatched identities', (org, batch) => {
    expect(render({ data, loading: false }, org, batch)).toContain('Current article quality is unavailable')
  })
  it('makes no completeness claim for missing HTML reasons', () => {
    const html = render({ loading: false, data: { ...data, parser_version: 'synthetic-html-v1', observation_route: 'html', observation_status: 'observed', reason_availability: 'not_recorded', reasons: [] } })
    expect(html).toContain('Parser-specific reasons are not recorded for this route')
    expect(html).not.toContain('Some affiliations may be missing')
  })
  it('makes no accuracy claim from an empty recorded reason list', () => {
    expect(render({ loading: false, data: { ...data, observation_status: 'observed', reasons: [] } })).toContain('does not establish complete coverage or accuracy')
  })
})
