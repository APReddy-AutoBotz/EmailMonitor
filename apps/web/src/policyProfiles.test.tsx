import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { Policy } from './models'
import { defaultSyntheticPolicyProfile, parseSyntheticPolicyProfile, pendingPolicyConfirmation, syntheticPolicy, syntheticPolicyProfiles, type SyntheticPolicyProfile } from './policyProfiles'
import { SyntheticPolicyProposal } from './views'

const now = Date.parse('2026-10-18T00:00:00Z')
const html = {
  execution_mode: 'fixture', purpose: 'academic_contact_research',
  allowed_hosts: ['synthetic.publisher.example'],
  allowed_operations: ['search', 'fetch_html', 'extract_contacts', 'retain_excerpt', 'export_contacts'],
  permission_reference: 'synthetic-fixtures-only', credential_reference: null,
  allowed_regions: ['test-only'], robots_handling: 'fixture_no_network',
  limits: { max_concurrent_requests: 1, min_request_interval_seconds: 5, max_articles_per_job: 500 },
  retention: { raw_hours: 24, excerpt_days: 30, contact_days: 90 },
  export_contacts_allowed: true, valid_until: '2026-10-19T00:00:00.000Z',
}

describe('closed synthetic policy proposals', () => {
  it('preserves the exact original HTML default and bounded expiry', () => {
    expect(defaultSyntheticPolicyProfile).toBe('html')
    expect(syntheticPolicy(undefined, now)).toEqual(html)
    expect(syntheticPolicyProfiles.map(p => p.id)).toEqual(['html', 'xml', 'html_browser', 'pdf'])
  })
  it('requires explicit authored PDF selection without download rights', () => {
    expect(syntheticPolicy('pdf', now)).toEqual({ ...html,
      allowed_operations: ['search', 'parse_fixture_pdf', 'extract_contacts', 'retain_excerpt', 'export_contacts'],
      retention: { raw_hours: 0, excerpt_days: 30, contact_days: 90 },
    })
    expect(syntheticPolicy(undefined, now).allowed_operations).not.toContain('parse_fixture_pdf')
    expect(syntheticPolicy('pdf', now).allowed_operations).not.toContain('fetch_pdf')
  })
  it('uses the exact explicit XML profile without unioning HTML rights', () => {
    expect(syntheticPolicy('xml', now)).toEqual({ ...html,
      allowed_operations: ['search', 'fetch_xml', 'extract_contacts', 'retain_excerpt', 'export_contacts'],
      retention: { raw_hours: 0, excerpt_days: 30, contact_days: 90 },
    })
  })
  it('adds only the explicit browser operation to the bounded HTML profile', () => {
    expect(syntheticPolicy('html_browser', now)).toEqual({ ...html, allowed_operations: [...html.allowed_operations, 'browser'] })
    expect(syntheticPolicy('html_browser', now).allowed_operations).not.toContain('fetch_xml')
  })
  it('refuses unknown runtime profile values rather than falling back', () => {
    for (const value of ['', 'provider_xml', 'fetch_xml', '__proto__', null, undefined, {}, 1]) {
      expect(() => parseSyntheticPolicyProfile(value)).toThrow('Unknown synthetic policy profile')
    }
    expect(() => syntheticPolicy('unknown' as SyntheticPolicyProfile)).toThrow('Unknown synthetic policy profile')
  })
  it('freezes nested permissions and retention and leaves current records unchanged', () => {
    const current = { ...html, version: 7, row_version: 9, state: 'approved' }
    const before = structuredClone(current)
    const proposal = syntheticPolicy(parseSyntheticPolicyProfile('xml'), now)
    for (const field of [proposal, proposal.allowed_hosts, proposal.allowed_operations, proposal.allowed_regions, proposal.limits, proposal.retention, syntheticPolicyProfiles, ...syntheticPolicyProfiles]) expect(Object.isFrozen(field)).toBe(true)
    expect(() => Object.assign(proposal.retention, { raw_hours: 24 })).toThrow()
    expect(() => Object.assign(proposal.allowed_operations, { 1: 'fetch_html' })).toThrow()
    expect(current).toEqual(before)
    expect(syntheticPolicy(undefined, now)).toEqual(html)
  })
  it('summarizes the actual pending record regardless of the proposal selection', () => {
    const pending: Policy = { ...html, version: 8, row_version: 3, state: 'pending_review', retention: { raw_hours: 7, excerpt_days: 8, contact_days: 9 } }
    syntheticPolicy('xml', now)
    const summary = pendingPolicyConfirmation(pending)
    expect(summary).toContain('version 8, revision 3')
    expect(summary).toContain('Operations: search, fetch_html, extract_contacts, retain_excerpt, export_contacts.')
    expect(summary).toContain('"raw_hours":7,"excerpt_days":8,"contact_days":9')
    expect(summary).toContain(html.valid_until)
    expect(summary).not.toContain('Operations: search, fetch_xml')
  })
})

describe('synthetic policy proposal form', () => {
  it('renders a labeled native selector with HTML default and separate explicit submission', () => {
    const onPropose = vi.fn()
    const markup = renderToStaticMarkup(<SyntheticPolicyProposal canManage onPropose={onPropose} />)
    expect(markup).toContain('<label>Synthetic policy profile<select>')
    expect(markup).toContain('<option value="html" selected="">Static HTML fixtures</option>')
    expect(markup).toContain('<option value="xml">Controlled provider XML</option>')
    expect(markup).toContain('<option value="html_browser">HTML + synthetic tooltip browser</option>')
    expect(markup).toContain('explicit job opt-in and a separately composed trusted browser worker')
    expect(markup).toContain('Proposed operations: search, fetch_html, extract_contacts, retain_excerpt, export_contacts.')
    expect(markup).toContain('raw 24 hours; excerpts 30 days; contacts 90 days')
    expect(markup).toContain('24 hours from submission')
    expect(markup).toContain('may fence jobs and downloads until separate approval')
    expect(markup).toContain('default worker refuses it')
    expect(markup).toContain('No real publisher rights')
    expect(markup).toContain('<button type="submit">Request synthetic source review</button>')
    expect(markup).not.toContain('Approve synthetic policy')
    expect(onPropose).not.toHaveBeenCalled()
  })
  it('renders neither selector nor submission for denied roles', () => {
    const onPropose = vi.fn()
    expect(renderToStaticMarkup(<SyntheticPolicyProposal canManage={false} onPropose={onPropose} />)).toBe('')
    expect(onPropose).not.toHaveBeenCalled()
  })
})
