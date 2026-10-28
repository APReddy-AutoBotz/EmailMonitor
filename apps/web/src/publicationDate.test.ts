import { describe, expect, it } from 'vitest'
import { publicationDateFilters } from './publicationDate'

describe('explicit publication-date requests', () => {
  it('omits empty filters to preserve old requests', () => {
    expect(publicationDateFilters('', '', '')).toEqual({})
  })
  it('keeps the chosen type and inclusive bounds in the request', () => {
    expect(publicationDateFilters('2026-01-15', '2026-01-15', 'online')).toEqual({ publication_date_type: 'online', publication_from: '2026-01-15', publication_to: '2026-01-15' })
    expect(publicationDateFilters('', '2026-12-31', 'issue')).toEqual({ publication_date_type: 'issue', publication_to: '2026-12-31' })
  })
  it('refuses missing type, missing bound, partial, invalid and unordered dates', () => {
    for (const [from, to, type] of [['2026-01-01', '', ''], ['', '', 'published'], ['2026-02', '', 'issue'], ['2026-02-30', '', 'published'], ['2026-02-02', '2026-02-01', 'online'], ['0000-01-01', '', 'issue'], ['2026-01-01', '', 'unknown']]) {
      expect(() => publicationDateFilters(from, to, type)).toThrow()
    }
  })
})
