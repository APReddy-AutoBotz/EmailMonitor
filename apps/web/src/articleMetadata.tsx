import type { ApiScope } from './client'
import { uid, useResource, type Resource } from './ui'

type Field = 'title' | 'journal' | 'publication_date' | 'doi'
export type ArticleMetadata = {
  view_version: 'article-metadata-v1'; organization_id: string; batch_id: string
  source_url: string; content_digest: string; parser_version: string
  observation_route: 'html' | 'browser_dom' | 'pdf' | 'article_xml'
  preferred_metadata: Record<Field, string | null>
  facts: { field: Field; value: string; date_type: 'published' | 'unspecified'; evidence: { locator: string; excerpt: string; kind?: string; page?: number; region_precision?: string } }[]
  fact_availability: 'recorded' | 'not_recorded'; multiple_value_fields: Field[]
  date_interpretation: 'retained_text_and_recorded_type_only'
}
const fields: Field[] = ['title', 'journal', 'publication_date', 'doi']
const labels: Record<Field, string> = { title: 'Title', journal: 'Journal', publication_date: 'Publication-date text', doi: 'DOI' }

export function ArticleMetadataPanel({ resource, organization, batch }: { resource: Resource<ArticleMetadata>; organization: string; batch: string }) {
  const data = resource.data
  const unavailable = resource.loading || resource.error || resource.stale || !data || data.organization_id !== organization || data.batch_id !== batch || data.view_version !== 'article-metadata-v1' || data.date_interpretation !== 'retained_text_and_recorded_type_only'
  return <section aria-label="Retained article metadata">
    <h4>Retained article metadata</h4>
    {unavailable ? <p role="status">{resource.loading ? 'Loading current article metadata…' : 'Current article metadata is unavailable. Refresh before relying on earlier values.'}</p> : <>
      <dl>{fields.map(field => <div key={field}><dt>{labels[field]}</dt><dd>{data.preferred_metadata[field] ?? 'Unobserved'}{data.multiple_value_fields.includes(field) && <span> · Multiple retained values; inspect citations below.</span>}</dd></div>)}</dl>
      <p>Publication-date text is shown as retained, with no inferred calendar date, date range or freshness. Recorded date types appear with their citations.</p>
      <p>Source: {data.source_url} · parser {data.parser_version} · route {data.observation_route}</p>
      {data.fact_availability === 'not_recorded' ? <p>Individual metadata citations were not recorded by this retained profile. Missing fields remain unobserved.</p> : data.facts.length === 0 ? <p>No metadata facts are retained for this article.</p> : <details><summary>Inspect all retained metadata values and citations</summary>
        <ol>{data.facts.map((fact, index) => <li key={index}><strong>{labels[fact.field]}:</strong> {fact.value}{fact.field === 'publication_date' && <p>Recorded date type: {fact.date_type === 'published' ? 'Published' : 'Unspecified'}</p>}
          <blockquote>{fact.evidence.excerpt || 'Excerpt unavailable'}</blockquote><p>{fact.evidence.locator}{fact.evidence.page !== undefined && ` · PDF page ${fact.evidence.page}`}{fact.evidence.region_precision && ` · ${fact.evidence.region_precision.replaceAll('_', ' ')}`}</p></li>)}</ol>
      </details>}
      <p>Content digest: {data.content_digest}. Reviewing an author-email association does not rewrite these article facts.</p>
    </>}
  </section>
}
export function CurrentArticleMetadata({ scope, batch }: { scope: ApiScope; batch: string }) {
  const resource = useResource<ArticleMetadata>(scope, '/association-batches/' + uid(batch) + '/article-metadata')
  return <ArticleMetadataPanel resource={scope.closed ? { loading: false } : resource} organization={scope.organization} batch={batch} />
}
