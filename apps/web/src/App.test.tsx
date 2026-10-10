import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('truthful scaffold', () => {
  it('renders the real application with explicit unavailable extraction', () => {
    const html = renderToStaticMarkup(<App />)
    expect(html).toContain('Extraction is not implemented')
    expect(html).toContain('No contact records are shown')
    expect(html).toContain('<fieldset disabled=""')
    expect(html).toContain('Start extraction (unavailable)')
    expect(html).toContain('id="keyword"')
    expect(html).toContain('id="url"')
    expect(html).not.toContain('mailto:')
    expect(html).not.toContain('<form')
  })
})
