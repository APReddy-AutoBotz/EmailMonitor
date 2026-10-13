import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import App from './App'
describe('truthful signed-out operator shell', () => {
  it('requires a real current session instead of inserting contacts or metrics', () => {
    const html = renderToStaticMarkup(<App />)
    expect(html).toContain('Operator workspace')
    expect(html).toContain('Checking the current session')
    expect(html).toContain('Synthetic offline environment')
    expect(html).toContain('No demo contacts are inserted')
    expect(html).toContain('href="#main"')
    expect(html).toContain('First author, corresponding author, observed email')
    expect(html).not.toContain('mailto:')
    expect(html).not.toContain('Mira Rao')
    expect(html).not.toContain('Export ready')
  })
})
