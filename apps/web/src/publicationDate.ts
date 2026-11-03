/** Request data only: connector capability is decided by the server plan. */
export function publicationDateFilters(from: string, to: string, dateType: string): Record<string, string> {
  if (!from && !to) {
    if (dateType) throw new Error('Choose at least one publication date bound')
    return {}
  }
  if (!['published', 'online', 'issue'].includes(dateType)) throw new Error('Choose a publication date type')
  const validDate = (value: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000-')) return false
    const parsed = new Date(value + 'T00:00:00Z')
    return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value
  }
  if ((from && !validDate(from)) || (to && !validDate(to))) throw new Error('Use full calendar dates')
  if (from && to && from > to) throw new Error('Publication date bounds must be ordered')
  return { publication_date_type: dateType, ...(from ? { publication_from: from } : {}), ...(to ? { publication_to: to } : {}) }
}
