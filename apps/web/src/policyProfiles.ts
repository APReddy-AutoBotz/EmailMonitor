import type { Policy } from './models'

export const syntheticPolicyProfiles = Object.freeze([
  Object.freeze({ id: 'html', label: 'Static HTML fixtures' }),
  Object.freeze({ id: 'xml', label: 'Controlled provider XML' }),
] as const)
export type SyntheticPolicyProfile = typeof syntheticPolicyProfiles[number]['id']
export const defaultSyntheticPolicyProfile: SyntheticPolicyProfile = 'html'

export function parseSyntheticPolicyProfile(value: unknown): SyntheticPolicyProfile {
  if (value === 'html' || value === 'xml') return value
  throw new Error('Unknown synthetic policy profile')
}

// Closed proposals only: never merge a selected profile with current server permissions.
export function syntheticPolicy(profile: SyntheticPolicyProfile = defaultSyntheticPolicyProfile, now = Date.now()) {
  const selected = parseSyntheticPolicyProfile(profile)
  return Object.freeze({
    execution_mode: 'fixture', purpose: 'academic_contact_research',
    allowed_hosts: Object.freeze(['synthetic.publisher.example']),
    allowed_operations: Object.freeze(['search', selected === 'html' ? 'fetch_html' : 'fetch_xml', 'extract_contacts', 'retain_excerpt', 'export_contacts']),
    permission_reference: 'synthetic-fixtures-only', credential_reference: null,
    allowed_regions: Object.freeze(['test-only']), robots_handling: 'fixture_no_network',
    limits: Object.freeze({ max_concurrent_requests: 1, min_request_interval_seconds: 5, max_articles_per_job: 500 }),
    retention: Object.freeze({ raw_hours: selected === 'html' ? 24 : 0, excerpt_days: 30, contact_days: 90 }),
    export_contacts_allowed: true, valid_until: new Date(now + 86400000).toISOString(),
  })
}

export function pendingPolicyConfirmation(current: Policy): string {
  return `Approve current pending policy version ${current.version}, revision ${current.row_version}. Operations: ${current.allowed_operations.join(', ')}. Retention (raw_hours, excerpt_days, contact_days): ${JSON.stringify(current.retention)}. Expiry: ${current.valid_until}. Synthetic use only; no real publisher rights are granted. Controlled provider XML requires a separately composed trusted controlled worker; the default worker refuses it.`
}
