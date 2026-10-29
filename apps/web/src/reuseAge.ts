/** Render an approximate age without inventing a missing or future observation time. */
export function reuseAge(value: string, now = Date.now()): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return 'age unavailable'
  const civil = value.slice(0, 19), civilTime = Date.parse(`${civil}Z`)
  if (civil.startsWith('0000-') || !Number.isFinite(civilTime) || new Date(civilTime).toISOString().slice(0, 19) !== civil) return 'age unavailable'
  const observed = Date.parse(value)
  if (!Number.isFinite(observed) || !Number.isFinite(now) || observed > now) return 'age unavailable'
  const hours = Math.floor((now - observed) / 3_600_000)
  if (hours === 0) return 'less than 1 hour old'
  if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} old`
  const days = Math.floor(hours / 24)
  return `${days} ${days === 1 ? 'day' : 'days'} old`
}
