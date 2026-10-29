import { describe, expect, it } from 'vitest'
import { reuseAge } from './reuseAge'

describe('reused observation age', () => {
  it('reports elapsed age without inferring missing or future time', () => {
    const now = Date.parse('2026-10-03T00:00:00Z')
    expect(reuseAge('2026-10-02T23:59:00Z', now)).toBe('less than 1 hour old')
    expect(reuseAge('2026-10-02T22:00:00Z', now)).toBe('2 hours old')
    expect(reuseAge('2026-10-01T00:00:00Z', now)).toBe('2 days old')
    expect(reuseAge('bad', now)).toBe('age unavailable')
    expect(reuseAge('2026-10-01T00:00:00', now)).toBe('age unavailable')
    expect(reuseAge('2026-02-30T00:00:00Z', now)).toBe('age unavailable')
    expect(reuseAge('2026-10-04T00:00:00Z', now)).toBe('age unavailable')
  })
})
