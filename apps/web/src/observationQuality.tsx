import type { ObservationQuality } from './models'
import { useResource, uid, type Resource } from './ui'
import type { ApiScope } from './client'

const descriptions: Record<string, string> = {
  page_cap: 'The PDF page limit was reached. Uninspected pages remain unresolved.',
  encrypted: 'The PDF is encrypted; no contact facts were retained.',
  corrupt: 'The PDF could not be parsed safely.',
  image_only_or_no_extractable_text: 'No supported machine-readable PDF text was available. OCR was not attempted.',
  unsupported_geometry: 'The PDF page geometry is unsupported.',
  unsupported_font_or_structure: 'The PDF font or document structure is unsupported.',
  resource_limit: 'The PDF parser resource limit was reached.',
  deadline: 'The PDF parser deadline was reached.',

  unsupported_affiliation: 'The parser recorded unsupported affiliation structure or mapping for this article. Some affiliations may be missing; this does not identify which author.',
  unsupported_email: 'Some email material could not be interpreted by this parser.',
  unstructured_contact: 'Unstructured contact material remains unresolved.',
  missing_full_text: 'Full text was unavailable in the retained observation.',
  unsupported_structure: 'The retained document structure was unsupported.',
  missing_article_identity: 'The required article identity was unavailable.',
  missing_authors: 'Supported author records were unavailable.',
  unsupported_author: 'Some author structure was unsupported.',
  ambiguous_reference: 'A structural reference was ambiguous or unsupported.',
}

export function ObservationQualityPanel({ resource, organization, batch }: { resource: Resource<ObservationQuality>; organization: string; batch: string }) {
  // Never present a previous quality response as current after refresh or failure.
  const data = resource.data
  const unavailable = resource.loading || resource.error || resource.stale || !data ||
    data.organization_id !== organization || data.batch_id !== batch ||
    data.view_version !== 'observation-quality-v1' || data.scope !== 'article' ||
    data.review_scope !== 'author_email_association'
  return <section aria-label="Article observation quality" className="notice">
    <h4>Article observation quality</h4>
    {unavailable ? <p role="status">{resource.loading ? 'Loading current article quality…' : 'Current article quality is unavailable. Do not assume extraction is complete.'}</p> : <>
      <p>Retained parser outcome: {data.observation_status.replaceAll('_', ' ')}. This describes the article, not an individual author.</p>
      {data.reason_availability === 'recorded' ? <>
        {data.reasons.length > 0 ? <ul>{data.reasons.map((reason, index) => <li key={index}>{descriptions[reason] ?? 'An unsupported parser reason was reported. Refresh before relying on this view.'}</li>)}</ul> : <p>No parser-specific reason was recorded. This does not establish complete coverage or accuracy.</p>}
      </> : <p>Parser-specific reasons are not recorded for this route.</p>}
    </>}
    <p>Missing affiliations remain unobserved, not confirmed absent. Accepting or correcting an author-email association does not resolve affiliation uncertainty or change the retained parser outcome.</p>
  </section>
}

// The caller keys this hook-owning child by organization, batch and refresh revision.
// A refresh therefore cannot render the old success before useEffect clears it.
export function CurrentObservationQuality({ scope, batch }: { scope: ApiScope; batch: string }) {
  const resource = useResource<ObservationQuality>(scope, '/association-batches/' + uid(batch) + '/observation-quality')
  return <ObservationQualityPanel resource={scope.closed ? { loading: false } : resource} organization={scope.organization} batch={batch} />
}
