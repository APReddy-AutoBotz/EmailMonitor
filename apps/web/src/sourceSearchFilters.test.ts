import { describe, expect, it } from 'vitest'
import { sourceSearchFilters } from './sourceSearchFilters'

describe('explicit source search filter requests', () => {
  it('preserves the omitted-default request identity and exact supplied text', () => {
    expect(sourceSearchFilters('', '')).toEqual({})
    expect(sourceSearchFilters(' Synthetic Journal A ', 'Review Article')).toEqual({ journal: ' Synthetic Journal A ', article_types: ['Review Article'] })
    expect(sourceSearchFilters('', 'research')).toEqual({ article_types: ['research'] })
  })
  it('refuses whitespace-only, controls and overlong text rather than silently broadening', () => {
    for (const [journal, type] of [['   ', ''], ['a\nb', ''], ['x'.repeat(301), ''], ['', ' '], ['', 'a\tb'], ['', 'x'.repeat(101)]]) {
      expect(() => sourceSearchFilters(journal, type)).toThrow()
    }
  })
})
