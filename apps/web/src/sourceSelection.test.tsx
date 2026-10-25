import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PlanInputGeneration, SourceFacts, SourceFilter, sourceSelectable, sourceState, syntheticSource } from './sourceSelection'
import { acceptedSelection, selectionExport, selectionSummary } from './selectionHandoff'

describe('existing registered source selection', () => {
  it('does not derive authority or health from labels or legacy catalog flags', () => {
    const source = { source_id: syntheticSource, enabled: true, execution_mode: 'fixture' }
    expect(sourceSelectable(source)).toBe(true)
    expect(sourceSelectable({ ...source, enabled: false })).toBe(false)
    expect(sourceSelectable({ ...source, execution_mode: 'live' })).toBe(false)
    expect(sourceSelectable({ ...source, source_id: 'elsevier_sciencedirect_v2' })).toBe(false)
    expect(sourceSelectable(undefined)).toBe(false)
    expect(sourceState({ source_id: syntheticSource })).toBe('Availability unverified')
    expect(sourceState({ ...source, enabled: false })).toBe('Temporarily unavailable')
    const html = renderToStaticMarkup(<SourceFacts source={source} />)
    expect(html).toContain('Unknown; no live certification')
    expect(html).toContain('Authored fixtures only')
    expect(html).not.toContain('<pre>')
  })
  it('offers all authorized sources and only the existing exact source', () => {
    const html = renderToStaticMarkup(<SourceFilter value={syntheticSource} change={() => {}} />)
    expect(html).toContain('All currently authorized sources')
    expect(html).toContain('value="synthetic-publisher" selected=""')
    expect(html).not.toContain('elsevier')
  })
  it('carries provenance into accepted selection and explicit export without cursor or preview', () => {
    const filters = { source: syntheticSource, job: '', query: '', state: 'needs_review', target: 'all', cursor: 'old', preview: 'old' }
    const accepted = acceptedSelection(filters)!
    expect(accepted.source).toBe(syntheticSource)
    const request = selectionExport(accepted)!
    expect(request.source_id).toBe(syntheticSource)
    expect(request.include_unresolved).toBe(false)
    expect(request).not.toHaveProperty('cursor')
    expect(request).not.toHaveProperty('preview')
    expect(selectionSummary(request)).toContain(syntheticSource)
    expect(selectionExport({ ...accepted, source: undefined })).not.toHaveProperty('source_id')
    expect(acceptedSelection({ ...filters, source: 'elsevier_sciencedirect_v2' })).toBeUndefined()
  })
  it('invalidates late plans for source A to empty to A and fresh session owners', () => {
    const owner = new PlanInputGeneration(), first = owner.observe('source=A;query=fixture')
    expect(owner.current(first)).toBe(true)
    owner.observe('source=;query=fixture')
    const second = owner.observe('source=A;query=fixture')
    expect(owner.current(first)).toBe(false)
    expect(owner.current(second)).toBe(true)
    expect(owner.observe('source=A;query=fixture')).toBe(second)
    owner.observe('source=A;query=changed')
    expect(owner.current(second)).toBe(false)
    expect(new PlanInputGeneration().current(first)).toBe(false)
  })
})
