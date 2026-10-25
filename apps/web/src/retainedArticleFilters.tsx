import type { ArticleOutcomePresence } from './models'

export function articleSelectionParams(job?: string | null, item?: string, presence: ArticleOutcomePresence = 'all', paper?: string) {
  return { ...(paper ? { paper_doi: paper } : {}), ...(job ? { job_id: job } : {}), ...(job && item ? { item_id: item } : {}), ...(presence !== 'all' ? { article_outcome_presence: presence } : {}) }
}

export function ArticlePresenceFilter({ value, change, disabled = false }: { value: ArticleOutcomePresence; change: (value: ArticleOutcomePresence) => void; disabled?: boolean }) {
  return <label>Article-outcome candidate presence<select value={value} disabled={disabled} onChange={event => change(event.target.value as ArticleOutcomePresence)}>
    <option value="all">All article outcomes</option>
    <option value="observed_candidate">Observed candidate</option>
    <option value="completed_without_candidate">Completed without a candidate</option>
    <option value="unresolved">Unresolved</option>
  </select></label>
}

export function ArticlePresenceHelp() {
  return <p>Candidate presence filters only the separate article-outcome dataset. Contact association, author and text filters remain independent. An observed candidate may be invalid, unmatched or rejected. Only a current complete supported observation with zero candidates counts as completed without a candidate; unavailable or incomplete observations are unresolved.</p>
}
