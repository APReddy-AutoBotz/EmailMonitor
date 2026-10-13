import { describe, expect, it } from 'vitest'
import { validatedSession } from './session'
const identity = '00000000-0000-4000-8000-000000000001'
const membership = { organization_id: identity, role: 'owner', organization_status: 'active', capabilities: ['organization.read'] }
const body = { identity_id: identity, csrf_token: 'nonce', synthetic_only: true, production_enabled: false, memberships: [membership] }
describe('session metadata syntax', () => {
  it('retains server capabilities as hints and permits no memberships', () => {
    expect(validatedSession(body).memberships).toEqual([membership])
    expect(validatedSession({ ...body, memberships: [] }).memberships).toEqual([])
  })
  it.each([null, {}, { ...body, production_enabled: true }, { ...body, synthetic_only: false }, { ...body, identity_id: 'fake' }, { ...body, csrf_token: '\nsecret' }, { ...body, memberships: [membership, membership] }, { ...body, memberships: [{ ...membership, role: 'superuser' }] }, { ...body, memberships: [{ ...membership, capabilities: null }] }])('refuses malformed and unsupported sessions', value => {
    expect(() => validatedSession(value)).toThrow()
  })
})
