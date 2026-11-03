import { describe, expect, it } from 'vitest'
import { reuseChoice } from './reuseChoice'

describe('explicit retained reuse choice', () => {
  it('leaves existing acquisition requests unchanged by default', () => {
    expect(reuseChoice(false, '')).toBeUndefined()
  })
  it('records the selected UTC cutoff without inventing a date', () => {
    expect(reuseChoice(true, '2024-02-29T10:20')).toEqual({ mode: 'verified_retained', fresh_since: '2024-02-29T10:20:00Z' })
    expect(reuseChoice(true, '2024-02-29T10:20:30')?.fresh_since).toBe('2024-02-29T10:20:30Z')
  })
  it.each(['', '2026-02-29T10:20', '2026-01-01', '2026-01-01T10:20Z', '0000-01-01T00:00'])('refuses incomplete or invalid cutoff %s', value => {
    expect(() => reuseChoice(true, value)).toThrow()
  })
})
