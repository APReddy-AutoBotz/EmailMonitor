import { describe, expect, it } from 'vitest'
import {
  defaultOutreachConfig,
  formatExportFilename,
  presetDescription,
  validateOutreachConfig,
  type OutreachExportConfig,
} from './outreachPresets'

describe('outreachPresets', () => {
  it('provides default instantly config', () => {
    const config = defaultOutreachConfig('instantly')
    expect(config.preset).toBe('instantly')
    expect(config.includeGdprNotice).toBe(true)
    expect(config.roleTarget).toBe('corresponding')
    expect(config.recencyThresholdYears).toBe(2)
    expect(config.suppressDisposable).toBe(true)
    expect(validateOutreachConfig(config)).toBe(true)
  })

  it('provides distinct descriptions for each preset', () => {
    expect(presetDescription('instantly')).toContain('Instantly.ai')
    expect(presetDescription('smartlead')).toContain('Smartlead.ai')
    expect(presetDescription('academic_crm')).toContain('CRM')
    expect(presetDescription('standard')).toContain('EmailMonitor')
  })

  it('formats filenames with preset and date', () => {
    expect(formatExportFilename('instantly', '2026-11-11')).toBe('emailmonitor-instantly-2026-11-11.csv')
    expect(formatExportFilename('smartlead', '2026-11-11')).toBe('emailmonitor-smartlead-2026-11-11.csv')
  })

  it('validates configuration correctly', () => {
    const valid = defaultOutreachConfig('smartlead')
    expect(validateOutreachConfig(valid)).toBe(true)

    const invalidRole = { ...valid, roleTarget: 'invalid' as unknown as OutreachExportConfig['roleTarget'] }
    expect(validateOutreachConfig(invalidRole)).toBe(false)

    const invalidYears = { ...valid, recencyThresholdYears: 0 }
    expect(validateOutreachConfig(invalidYears)).toBe(false)
  })
})
