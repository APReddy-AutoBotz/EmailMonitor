/**
 * Cold outreach export presets and configuration for Open Access publishers.
 */

export type OutreachPreset = 'instantly' | 'smartlead' | 'academic_crm' | 'standard'

export interface OutreachExportConfig {
  preset: OutreachPreset
  includeGdprNotice: boolean
  recencyThresholdYears: number
  roleTarget: 'corresponding' | 'first' | 'all'
  suppressDisposable: boolean
}

export function defaultOutreachConfig(preset: OutreachPreset = 'instantly'): OutreachExportConfig {
  return {
    preset,
    includeGdprNotice: true,
    recencyThresholdYears: 2,
    roleTarget: 'corresponding',
    suppressDisposable: true,
  }
}

export function presetDescription(preset: OutreachPreset): string {
  switch (preset) {
    case 'instantly':
      return 'Instantly.ai lead import format with custom paper title, journal, DOI, and GDPR Article 6(1)(f) receipt.'
    case 'smartlead':
      return 'Smartlead.ai lead import format with recency scoring and custom variables.'
    case 'academic_crm':
      return 'Comprehensive academic publisher CRM format with ORCID, affiliations, and full provenance.'
    case 'standard':
      return 'Standard formula-safe EmailMonitor research export.'
  }
}

export function formatExportFilename(preset: OutreachPreset, dateStr: string = '2026-11-11'): string {
  return `emailmonitor-${preset}-${dateStr}.csv`
}

export function validateOutreachConfig(config: OutreachExportConfig): boolean {
  return (
    ['instantly', 'smartlead', 'academic_crm', 'standard'].includes(config.preset) &&
    ['corresponding', 'first', 'all'].includes(config.roleTarget) &&
    config.recencyThresholdYears >= 1 &&
    config.recencyThresholdYears <= 10
  )
}
