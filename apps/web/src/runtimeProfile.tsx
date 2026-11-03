import { sessionRequest } from './client'

export type RuntimeProfile = {
  profile: 'authored-html-service-reference' | 'controlled-xml-service-reference'
  production_ready: false
  xml_available: boolean
  pdf_available: false
  dynamic_browser_available: false
  live_sources_available: false
}

// An informational installed profile is never source-policy or tenant authority.
// Unknown or inconsistent profiles must not turn into advertised capabilities.
export function validatedRuntimeProfile(value: unknown): RuntimeProfile | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const data = value as Record<string, unknown>
  if (!['authored-html-service-reference', 'controlled-xml-service-reference'].includes(String(data.profile))
    || data.xml_available !== (data.profile === 'controlled-xml-service-reference')
    || ['production_ready', 'pdf_available', 'dynamic_browser_available', 'live_sources_available'].some(key => data[key] !== false)) return undefined
  return { profile: data.profile as RuntimeProfile['profile'], xml_available: data.xml_available as boolean,
    production_ready: false, pdf_available: false, dynamic_browser_available: false, live_sources_available: false }
}

export async function optionalRuntimeProfile(signal: AbortSignal): Promise<RuntimeProfile | undefined> {
  try { return validatedRuntimeProfile(await sessionRequest<unknown>('/runtime-profile', signal)) }
  catch { return undefined } // Default fixture applications intentionally do not expose this endpoint.
}

export function RuntimeProfileNotice({ profile, preflight = false }: { profile?: RuntimeProfile; preflight?: boolean }) {
  if (!profile) return preflight ? <p role="note">Installed runtime capabilities are unverified. Existing fixture planning remains available; the server must validate the source policy and execution route.</p> : null
  return <section className="notice" aria-label={preflight ? 'Runtime preflight' : 'Installed runtime capabilities'}>
    <h4>{preflight ? 'Runtime preflight' : 'Installed runtime capabilities'}</h4>
    <p>{profile.xml_available
      ? 'Controlled XML is available in this installed runtime only with a separate, explicitly approved synthetic XML source policy. Runtime availability does not grant source permission.'
      : 'This installed runtime supports authored HTML fixtures. Controlled XML is unavailable; approving an XML policy does not enable XML execution in this runtime.'}</p>
    <p>PDF, dynamic browser and live sources are unavailable in this installed runtime. This reference profile is not production-ready.</p>
    {preflight && <p>Check the current policy in Sources before launch. Server planning and launch checks remain authoritative; review and export permissions are unchanged.</p>}
  </section>
}
