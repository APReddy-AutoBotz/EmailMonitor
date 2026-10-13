/** Literal metadata only; never an image URL, HTML fragment or permission. */
import type { TenantConfiguration } from './models'
export function currentBrand(configuration: TenantConfiguration | undefined, organization: string): { label: string | null; accent: string } {
  if (!configuration || configuration.organization_id !== organization) return { label: null, accent: '#155e63' }
  const value = configuration.branding
  const label = typeof value.label === 'string' && value.label.length <= 80 && value.label.trim() && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value.label) ? value.label : null
  return { label, accent: typeof value.accent_color === 'string' && value.accent_color.length === 7 && /^#[0-9a-f]{6}$/.test(value.accent_color) ? value.accent_color : '#155e63' }
}
