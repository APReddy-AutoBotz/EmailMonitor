import { describe, expect, it } from 'vitest'
import indexHtml from '../index.html?raw'
import styles from './styles.css?raw'

// The operator UI must make no third-party requests: the production CSP is
// style-src/script-src 'self', the isolated browser acceptance has no network and
// refuses cross-origin stylesheets, and remote fonts would leak operator IPs.
const external = /(?:https?:)?\/\/(?!localhost|127\.0\.0\.1)[a-z0-9.-]+\.[a-z]{2,}/i

describe('no external assets', () => {
  it('index.html references no remote stylesheet, font, script or preconnect', () => {
    expect(indexHtml).not.toMatch(/<link[^>]+href="https?:/i)
    expect(indexHtml).not.toMatch(/<script[^>]+src="https?:/i)
  })
  it('styles.css imports and fetches nothing remote', () => {
    expect(styles).not.toMatch(/@import/i)
    const urls = styles.match(/url\([^)]*\)/gi) ?? []
    expect(urls.filter(url => external.test(url))).toEqual([])
  })
})
