import { validSourceSelection } from './sourceSelection'
import type { ArticleOutcomePresence, ExportOptions } from './models'
import { isSupportedPaperDoi } from './retainedArticleFilters'

export type ContactFilters = { source?: string; paper?: string; query: string; state: string; target: string; job: string; item?: string; presence?: ArticleOutcomePresence }
const uuid = (value: string) => value.length === 36 && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
export function validSelection(value: ContactFilters): boolean {
  return validSourceSelection(value.source) && ['accepted', 'needs_review', 'unmatched', 'rejected'].includes(value.state) && (!value.job || uuid(value.job)) && (!value.item || (!!value.job && uuid(value.item))) &&
    (!value.paper || isSupportedPaperDoi(value.paper)) && value.query.length <= 100 &&
    ['all', 'first', 'corresponding'].includes(value.target) &&
    ['all', 'observed_candidate', 'completed_without_candidate', 'unresolved'].includes(value.presence ?? 'all')
}
// Whitelist selectors only: no cursor, evidence, preview, acceptance or authorization travels.
export function acceptedSelection(value: ContactFilters): ContactFilters | undefined {
  if (!validSelection(value)) return undefined
  return { ...(value.source ? { source: value.source } : {}), job: value.job, item: value.item, paper: value.paper, query: value.query, target: value.target, presence: value.presence, state: 'accepted' }
}
export const initialExport: ExportOptions = { job_id: null, format: 'xlsx', purpose: 'academic_contact_research', include_unresolved: false, include_article_outcomes: true, author_target: 'all', query: '', ttl_seconds: 86400, optional_contact_fields: ['affiliations', 'article_title'] }
export function selectionExport(value: ContactFilters): ExportOptions | undefined {
  if (value.state !== 'accepted' || !validSelection(value)) return undefined
  return { ...initialExport, ...(value.source ? { source_id: value.source as 'synthetic-publisher' } : {}), job_id: value.job || null, item_id: value.item || undefined, paper_doi: value.paper || undefined, author_target: value.target as ExportOptions['author_target'], query: value.query, article_outcome_presence: value.presence === 'all' ? undefined : value.presence }
}
export function selectionSummary(value: ExportOptions): string {
  return `Accepted contacts; source: ${value.source_id || 'all currently authorized sources'}; job: ${value.job_id || 'all authorized jobs'}; article: ${value.item_id || 'all matching articles'}; paper: ${value.paper_doi || 'all observed papers'}; author role: ${value.author_target}; literal text: ${value.query || '(none)'}. Outcome-only candidate presence: ${value.article_outcome_presence || 'all'}.`
}
// Monotonic ownership prevents a late A response after edits A → B → A.
export class PreviewGeneration {
  private generation = 0
  invalidate() { this.generation += 1 }
  begin() { this.invalidate(); return this.generation }
  current(generation: number) { return generation === this.generation }
}
