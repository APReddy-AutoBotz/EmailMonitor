import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Time } from './ui'

const format = Date.prototype.toLocaleString
beforeEach(() => {
  // A deterministic browser locale, retaining the real Intl timezone/DST rules.
  vi.spyOn(Date.prototype, 'toLocaleString').mockImplementation(function (this: Date, optionsLocale, options) {
    void optionsLocale
    return format.call(this, 'en-GB', options)
  })
})
afterEach(() => vi.restoreAllMocks())

const display = (instant: string, zone?: string) => renderToStaticMarkup(<Time value={instant} zone={zone} />)

describe('NFR-012 UTC-derived time with explicit timezone', () => {
  it('labels the default as UTC and preserves the machine-readable instant', () => {
    const markup = display('2026-10-26T00:15:00Z')
    expect(markup).toContain('dateTime="2026-10-26T00:15:00Z"')
    expect(markup).toContain('26/10/2026, 00:15:00 (UTC)')
  })

  it('shows a fractional-offset timezone and local calendar rollover without changing the instant', () => {
    const markup = display('2026-10-25T20:45:00Z', 'Asia/Kolkata')
    expect(markup).toContain('dateTime="2026-10-25T20:45:00Z"')
    expect(markup).toContain('26/10/2026, 02:15:00 (Asia/Kolkata)')
  })

  it('skips the nonexistent local hour at the spring DST transition', () => {
    expect(display('2026-03-08T06:59:00Z', 'America/New_York')).toContain('08/03/2026, 01:59:00 (America/New_York)')
    expect(display('2026-03-08T07:00:00Z', 'America/New_York')).toContain('08/03/2026, 03:00:00 (America/New_York)')
  })

  it('preserves distinct UTC instants across the repeated autumn local hour', () => {
    const first = display('2026-11-01T05:30:00Z', 'America/New_York')
    const second = display('2026-11-01T06:30:00Z', 'America/New_York')
    for (const markup of [first, second]) expect(markup).toContain('01/11/2026, 01:30:00 (America/New_York)')
    expect(first).toContain('dateTime="2026-11-01T05:30:00Z"')
    expect(second).toContain('dateTime="2026-11-01T06:30:00Z"')
    expect(first).not.toBe(second)
  })

  it('uses the newly selected display zone without modifying the source value', () => {
    const value = '2026-10-26T00:15:00Z'
    expect(display(value, 'UTC')).toContain('26/10/2026, 00:15:00 (UTC)')
    expect(display(value, 'America/Los_Angeles')).toContain('25/10/2026, 17:15:00 (America/Los_Angeles)')
    expect(value).toBe('2026-10-26T00:15:00Z')
  })

  it('labels unsupported configuration as a UTC fallback rather than a successful local conversion', () => {
    const markup = display('2026-10-26T00:15:00+05:30', 'Unknown/Fixture')
    expect(markup).toContain('2026-10-25T18:45:00.000Z (UTC fallback; unsupported configured timezone)')
    expect(markup).toContain('dateTime="2026-10-26T00:15:00+05:30"')
  })

  it.each(['', 'not-a-time'])('keeps an invalid instant unknown: %j', value => {
    expect(display(value, 'UTC')).toBe('<span>Unknown time</span>')
  })
})
