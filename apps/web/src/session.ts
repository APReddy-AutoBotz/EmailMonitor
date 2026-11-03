import { ApiError } from './client'
import type { Session } from './models'
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/
const roles = new Set(['owner', 'admin', 'data_steward', 'operator', 'reviewer', 'viewer'])
/** Environment/session syntax only. The server remains the authorization authority. */
export function validatedSession(value: unknown): Session {
  if (!value || typeof value !== 'object') throw new ApiError(0, 'Unsupported session response.')
  const body = value as Record<string, unknown>
  if (body.synthetic_only !== true || body.production_enabled !== false || typeof body.identity_id !== 'string' || !uuid.test(body.identity_id)
    || typeof body.csrf_token !== 'string' || !body.csrf_token || body.csrf_token.length > 256 || /[\x00-\x20\x7f]/.test(body.csrf_token)
    || !Array.isArray(body.memberships) || body.memberships.length > 1000) throw new ApiError(0, 'Unsupported environment or session response.')
  const seen = new Set<string>()
  for (const value of body.memberships) {
    if (!value || typeof value !== 'object') throw new ApiError(0, 'Unsupported membership response.')
    const member = value as Record<string, unknown>
    if (typeof member.organization_id !== 'string' || !uuid.test(member.organization_id) || seen.has(member.organization_id)
      || typeof member.role !== 'string' || !roles.has(member.role) || typeof member.organization_status !== 'string'
      || !Array.isArray(member.capabilities) || member.capabilities.length > 100 || member.capabilities.some(item => typeof item !== 'string' || !/^[a-z_.]+$/.test(item))) throw new ApiError(0, 'Unsupported membership response.')
    seen.add(member.organization_id)
  }
  return body as Session
}
