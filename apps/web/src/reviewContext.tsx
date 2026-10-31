import { useEffect, useRef, useState } from 'react'
import { errorMessage, type ApiScope } from './client'
import type { Contact } from './models'

type ContextView = {
  kind: 'transient_context_only'; organization_id: string; target_batch_id: string
  target_association_id: string; target_revision: number; source_batch_id: string
  source_url: string; source_digest: string; source_parser_version: string; source_route: string
  evidence: { id: string; method: string; locator: string; excerpt: string; page: number | null }
  attached: false; identity_verified: false; acceptance_changed: false; export_changed: false
}

const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i
export function currentContext(value: unknown, scope: ApiScope, target: Contact, batch: string, evidence: string): value is ContextView {
  if (!value || typeof value !== 'object' || scope.closed) return false
  const data = value as Partial<ContextView>, item = data.evidence
  return data.kind === 'transient_context_only' && data.organization_id === scope.organization
    && target.organization_id === scope.organization && data.target_batch_id === target.batch_id
    && data.target_association_id === target.association_id && data.target_revision === target.revision
    && data.source_batch_id === batch && item?.id === evidence
    && data.attached === false && data.identity_verified === false && data.acceptance_changed === false && data.export_changed === false
    && typeof data.source_url === 'string' && typeof data.source_parser_version === 'string'
    && typeof data.source_route === 'string' && typeof data.source_digest === 'string' && /^[a-f0-9]{64}$/.test(data.source_digest)
    && typeof item.method === 'string' && typeof item.locator === 'string' && typeof item.excerpt === 'string'
    && (item.page === null || (Number.isSafeInteger(item.page) && Number(item.page) > 0))
}

export function ReviewContext({ scope, target }: { scope: ApiScope; target: Contact }) {
  const [sourceBatch, setSourceBatch] = useState(''), [evidence, setEvidence] = useState('')
  const [result, setResult] = useState<ContextView>(), [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const generation = useRef(0)
  useEffect(() => () => { generation.current += 1 }, [scope, target.batch_id, target.association_id, target.revision])
  const invalidate = () => { generation.current += 1; setResult(undefined); setError(''); setLoading(false) }
  const submit = async () => {
    invalidate()
    if (!uuid.test(sourceBatch) || !uuid.test(evidence) || sourceBatch.toLowerCase() === target.batch_id.toLowerCase()) {
      setError('Enter a different source batch and a retained evidence identifier.'); return
    }
    const batch = sourceBatch.toLowerCase(), citation = evidence.toLowerCase(), current = generation.current
    setLoading(true)
    try {
      const response = await scope.write<unknown>('/review-context/view', {
        target_batch_id: target.batch_id, target_association_id: target.association_id,
        expected_revision: target.revision, source_batch_id: batch, source_evidence_id: citation,
      })
      if (current !== generation.current || scope.closed) return
      if (!currentContext(response, scope, target, batch, citation)) throw new Error('Unavailable')
      setResult(response)
    } catch (failure) {
      if (current === generation.current && !scope.closed) setError(errorMessage(failure))
    } finally { if (current === generation.current && !scope.closed) setLoading(false) }
  }
  return <section aria-label="Temporary source context">
    <h4>View a citation from another observation</h4>
    <p>This temporary context is not attached or saved. It does not establish the same person, change review or affect exports. Both observations must remain currently authorized.</p>
    <form onSubmit={event => { event.preventDefault(); void submit() }}>
      <label>Other observation batch ID<input value={sourceBatch} maxLength={36} onChange={event => { invalidate(); setSourceBatch(event.target.value) }} /></label>
      <label>Other observation evidence ID<input value={evidence} maxLength={36} onChange={event => { invalidate(); setEvidence(event.target.value) }} /></label>
      <button type="submit" disabled={loading || scope.closed}>View temporary context</button>
      <button type="button" onClick={invalidate}>Clear context</button>
    </form>
    {loading && <p role="status">Checking both observations…</p>}{error && <p role="alert">{error}</p>}
    {result && currentContext(result, scope, target, sourceBatch.toLowerCase(), evidence.toLowerCase()) && <div>
      <p>Other source: {result.source_url} · {result.source_route} · parser {result.source_parser_version}</p>
      <blockquote>{result.evidence.excerpt || 'No retained excerpt'}</blockquote>
      <p>{result.evidence.method} · {result.evidence.locator}{result.evidence.page !== null && ` · page ${result.evidence.page}`}</p>
      <p>Source digest: {result.source_digest}. Refresh to check current authority again.</p>
    </div>}
  </section>
}
