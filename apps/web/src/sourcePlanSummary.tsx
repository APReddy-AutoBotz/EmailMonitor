import type { Job } from './models'

const record = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
const text = (value: unknown): string => typeof value === 'string' && value.length > 0 ? value : 'Unavailable'
const count = (value: unknown): string => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? String(value) : 'Unavailable'
const flag = (value: unknown): string => value === true ? 'Requested' : value === false ? 'Not requested' : 'Unavailable'

const classification: Record<string, string> = {
  article: 'Single article', search_results: 'Search results',
  needs_refinement: 'Needs refinement', unsupported: 'Unsupported',
}
const reasons: Record<string, string> = {
  fixture_filters_unavailable: 'This source cannot apply the requested filters. Change or remove them and create a new plan.',
  fixture_topic_unavailable: 'This fixture source does not support the requested topic.',
  homepage_requires_keyword_or_scoped_url: 'Use a keyword or a scoped search or article URL.',
  source_onboarding_required: 'This source requires onboarding before extraction.',
  unsafe_or_unonboarded_url: 'This URL is unsafe or its source is not onboarded.',
  fixture_route_unavailable: 'This fixture route is unavailable.',
  fixture_pdf_unavailable: 'This PDF is not an available authored fixture.',
  pdf_disabled: 'The authored PDF fixture option was not requested.',
  retained_reuse_unavailable: 'This input cannot use retained-observation reuse. Fresh acquisition was not substituted.',
  supported_fixture: 'The input matches a supported synthetic fixture.',
  controlled_provider_fixture: 'The input matches a controlled provider fixture; its separate policy and worker requirements still apply.',
  authored_local_pdf: 'The input matches an authored local PDF fixture; its separate policy and parser requirements still apply.',
  retained_reuse_authored: 'The input matches an authored retained-reuse fixture; current authority and eligibility still apply.',
}
const authors: Record<string, string> = {
  both: 'First and corresponding, independently', first: 'First', corresponding: 'Corresponding', all: 'All observed authors',
}
const mapped = (values: Record<string, string>, value: unknown): string =>
  typeof value === 'string' && Object.hasOwn(values, value) ? values[value]! : 'Unavailable'
const planDetail = (plan: Record<string, unknown>): Record<string, unknown> | undefined =>
  plan.plan === undefined ? plan : record(plan.plan)

export function launchableSourcePlan(plan: Record<string, unknown>): boolean {
  const value = planDetail(plan)?.classification
  return plan.persisted !== false && (value === 'article' || value === 'search_results')
}

/** Display only returned plan fields and the immutable request returned with the job. */
export function SourcePlanSummary({ plan, job }: { plan: Record<string, unknown>; job: Job }) {
  const detail = planDetail(plan)
  const request = record(job.request)
  const input = record(request?.input)
  const options = record(request?.options)
  const filters = record(request?.filters)
  const reuse = record(request?.reuse)
  const checkpoint = record(plan.checkpoint)
  const status = mapped(classification, detail?.classification)
  const reason = typeof detail?.reason === 'string' && Object.hasOwn(reasons, detail.reason)
    ? reasons[detail.reason] : 'The server did not provide a recognized explanation. See the technical plan details.'
  const source = text(plan.source_id ?? input?.source_id)
  const hasDates = filters && (filters.publication_from !== undefined || filters.publication_to !== undefined)
  return <>
    <p><strong>{status}.</strong> {reason}</p>
    <dl aria-label="Plan summary" className="plan-summary">
      <div><dt>Source identity</dt><dd>{source}</dd></div>
      <div><dt>Planned start URL</dt><dd>{text(detail?.start_url)}</dd></div>
      <div><dt>Original query</dt><dd>{text(detail?.original_query)}</dd></div>
      <div><dt>Effective query</dt><dd>{text(detail?.effective_query)}</dd></div>
      <div><dt>Requested article limit</dt><dd>{count(options?.max_articles)}</dd></div>
      <div><dt>Effective article cap</dt><dd>{count(plan.max_articles)}</dd></div>
      <div><dt>Maximum result pages</dt><dd>{count(plan.max_pages)}</dd></div>
      <div><dt>Author selection</dt><dd>{mapped(authors, options?.author_target)}</dd></div>
      <div><dt>Browser work</dt><dd>{flag(options?.allow_browser)}</dd></div>
      <div><dt>Authored PDF fixtures</dt><dd>{flag(options?.allow_pdf)}</dd></div>
      <div><dt>Policy version at planning</dt><dd>{count(plan.policy_version)}</dd></div>
      <div><dt>Source-reported total at planning</dt><dd>{count(checkpoint?.reported_total)}</dd></div>
      <div><dt>Article URLs listed at planning</dt><dd>{Array.isArray(checkpoint?.articles) && checkpoint.articles.every(value => typeof value === 'string') ? count(checkpoint.articles.length) : 'Unavailable'}</dd></div>
    </dl>
    {hasDates ? <p>Requested publication date: {text(filters.publication_date_type)}; from {text(filters.publication_from)} to {text(filters.publication_to)} (inclusive where supplied). A request is not proof that the source applied the filter.</p> : null}
    {reuse ? <p>Retained reuse: {text(reuse.mode)}; fresh since {text(reuse.fresh_since)}. Eligibility is checked by the server.</p> : null}
    {plan.persisted === false ? <p>The server did not persist this plan. It cannot be launched; revise the input and create a new plan.</p> : null}
    <p>Listed URLs are not verified completed articles. Source-reported totals and discovered URLs are different; this is a planning snapshot. Estimated units and cost are unavailable. A matching input is not permission to acquire it; current source policy, capabilities, retention and server limits still apply at launch and execution.</p>
    <details><summary>Technical plan details</summary><pre>{JSON.stringify(plan, null, 2)}</pre></details>
  </>
}
