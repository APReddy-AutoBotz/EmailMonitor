export function reuseChoice(enabled: boolean, utcInput: string): { mode: 'verified_retained'; fresh_since: string } | undefined {
  if (!enabled) return undefined
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(utcInput)) throw new Error('Choose a complete UTC freshness cutoff')
  const full = utcInput.length === 16 ? `${utcInput}:00` : utcInput
  const parsed = new Date(`${full}Z`)
  if (full.startsWith('0000-') || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 19) !== full) throw new Error('Choose a valid UTC freshness cutoff')
  return { mode: 'verified_retained', fresh_since: `${full}Z` }
}
