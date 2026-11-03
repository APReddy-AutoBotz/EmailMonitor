import { describe, expect, it } from 'vitest'
import { currentBrand } from './branding'
import type { TenantConfiguration } from './models'
const organization = '11111111-1111-4111-8111-111111111111'
const configuration = { organization_id: organization, branding: { label: '<literal authored label>', accent_color: '#123456', logo_reference: null } } as TenantConfiguration
describe('literal current-tenant branding', () => {
  it('retains literal text and a closed color grammar', () => {
    expect(currentBrand(configuration, organization)).toEqual({ label: '<literal authored label>', accent: '#123456' })
  })
  it('clears prior organization metadata', () => {
    expect(currentBrand(configuration, 'other')).toEqual({ label: null, accent: '#155e63' })
    expect(currentBrand(undefined, organization)).toEqual({ label: null, accent: '#155e63' })
  })
  it('refuses executable colors and control-bearing labels', () => {
    const invalid = { ...configuration, branding: { ...configuration.branding, label: 'author\u202elabel', accent_color: 'url(external)' } }
    expect(currentBrand(invalid, organization)).toEqual({ label: null, accent: '#155e63' })
  })
})
