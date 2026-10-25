import type { Source } from './models'

export const syntheticSource = 'synthetic-publisher' as const
export type RetainedSource = typeof syntheticSource
export const validSourceSelection = (value?: string) => value === undefined || value === '' || value === syntheticSource
export function SourceFilter({ value, change }: { value?: string; change: (value: RetainedSource | undefined) => void }) {
  return <label>Retained source<select value={value ?? ''} onChange={event => { if (event.target.value === '' || event.target.value === syntheticSource) change(event.target.value || undefined) }}>
    <option value="">All currently authorized sources</option><option value={syntheticSource}>Synthetic Publisher · registered provenance</option>
  </select></label>
}
export function sourceState(source: Source): string {
  if (source.enabled === false) return 'Temporarily unavailable'
  if (source.enabled !== true || source.execution_mode !== 'fixture') return 'Availability unverified'
  return source.source_id === syntheticSource ? 'Registered fixture source; server planning required' : 'Unsupported by this fixture workflow'
}
export function sourceSelectable(source: Source | undefined): boolean {
  return source?.source_id === syntheticSource && source.enabled === true && source.execution_mode === 'fixture'
}
export function SourceFacts({ source }: { source: Source }) {
  return <dl><div><dt>Registered source</dt><dd>{source.source_id}</dd></div>
    <div><dt>Availability</dt><dd>{sourceState(source)}</dd></div>
    <div><dt>Access mode</dt><dd>{source.execution_mode === 'fixture' ? 'Authored fixtures only; no live acquisition' : 'Unverified'}</dd></div>
    <div><dt>Health</dt><dd>Unknown; no live certification or canary is implied</dd></div>
    <div><dt>Fixture capabilities</dt><dd>{source.source_id === syntheticSource ? 'Registered keyword and article inputs; HTML, controlled XML, tooltip and local PDF routes each require their existing policy and worker composition.' : 'Unsupported by this fixture workflow'}</dd></div>
    <div><dt>Limitations</dt><dd>Publication-date, journal and article-type filters are unavailable. A route or parser is not a separate registered source.</dd></div></dl>
}

// Returning to the same inputs must not revive a response from an earlier request.
export class PlanInputGeneration {
  private signature?: string
  private generation = 0
  observe(signature: string): number {
    if (signature !== this.signature) { this.signature = signature; this.generation += 1 }
    return this.generation
  }
  current(value: number): boolean { return value === this.generation }
}
