import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Context } from './ui'
import { Dashboard, ResearchInputHelp, Wizard } from './views'

function context(): Context {
  return {
    scope: new ApiScope('00000000-0000-0000-0000-000000000001', 'test-only'),
    revision: 0, refresh: vi.fn(), act: vi.fn(), confirm: vi.fn(), can: () => false,
    identity: 'test-only', zone: 'UTC', openJob: vi.fn(),
  }
}

describe('bounded synthetic input help', () => {
  it('distinguishes exact static and controlled keywords without promising arbitrary search', () => {
    const markup = renderToStaticMarkup(<ResearchInputHelp mode="keyword" />)
    expect(markup).toContain('Myocardial Infarction for static HTML fixtures')
    expect(markup).toContain('Controlled provider journey for controlled synthetic XML')
    expect(markup).toContain('Arbitrary queries do not reuse these results')
    expect(markup).not.toContain('supports exactly Myocardial Infarction')
  })

  it('shows durable synthetic DOI/PII URLs and preserves unsupported-input boundaries', () => {
    const markup = renderToStaticMarkup(<ResearchInputHelp mode="url" />)
    for (const route of ['provider-doi.xml', 'provider-pii.xml']) {
      expect(markup).toContain('https://synthetic.publisher.example/' + route)
    }
    expect(markup).toContain('Raw DOI links and provider API URLs are not supported inputs')
    expect(markup).toContain('A homepage requires refinement')
    expect(markup).toContain('an unknown domain is not an unrestricted crawl')
    expect(markup).not.toContain('six authored publisher routes')
    expect(markup).not.toContain('href=')
  })

  it('renders policy and worker prerequisites without enabling acquisition for denied roles', () => {
    const c = context()
    const markup = renderToStaticMarkup(<Wizard context={c} />)
    expect(markup).toContain('Controlled provider journey for controlled synthetic XML')
    expect(markup).toContain('All inputs require server planning and current source approval')
    expect(markup).toContain('explicit review and separate approval in Sources')
    expect(markup).toContain('a separately composed trusted worker; the default worker refuses it')
    expect(markup).toContain('First authors never inherit a correspondent’s address')
    expect(markup).toContain('<button type="submit" disabled="">Create and validate plan</button>')
    for (const limit of ['PDF acquisition unavailable', 'Browser acquisition unavailable in this operator worker', 'OCR unavailable', 'Wider web unavailable']) expect(markup).toContain(limit)
    expect(c.act).not.toHaveBeenCalled()
  })

  it('keeps Dashboard limits consistent with the controlled catalog-only inputs', () => {
    const markup = renderToStaticMarkup(<Dashboard context={context()} navigate={vi.fn()} />)
    expect(markup).toContain('static HTML fixtures and a controlled provider XML journey with registered DOI/PII article URLs')
    expect(markup).toContain('an explicitly reviewed synthetic XML policy; the default worker refuses it')
    expect(markup).toContain('Arbitrary DOI/provider API URLs, live publisher access, PDF acquisition')
    expect(markup).toContain('Accepted association does not mean a globally resolved person, live mailbox or outreach approval')
    expect(markup).not.toContain('PDF/DOI acquisition')
  })
})
