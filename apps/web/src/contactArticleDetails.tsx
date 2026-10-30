import { useLayoutEffect, useRef } from 'react'
import { CurrentArticleMetadata } from './articleMetadata'
import type { ApiScope } from './client'
import type { Contact, Page } from './models'
import type { Resource } from './ui'

export type ArticleDetailsSelection = { scope: ApiScope; generation: number; contact: Contact }

export class ArticleDetailsGeneration {
  private scope?: ApiScope
  private signature?: string
  private generation = 0
  observe(scope: ApiScope, signature: string): number {
    if (scope !== this.scope || signature !== this.signature) {
      this.scope = scope; this.signature = signature; this.generation += 1
    }
    return this.generation
  }
  current(value: number): boolean { return value === this.generation }
}

/** A selection is usable only while the same current-authorized page owns that row. */
export function currentArticleSelection(
  selection: ArticleDetailsSelection | undefined,
  scope: ApiScope,
  generation: number,
  contacts: Resource<Page<Contact>>,
  blocked: boolean,
): selection is ArticleDetailsSelection {
  if (!selection || selection.scope !== scope || scope.closed || selection.generation !== generation
    || blocked || contacts.loading || contacts.error || contacts.stale || !contacts.data) return false
  const selected = selection.contact
  return selected.organization_id === scope.organization && contacts.data.items.some(row =>
    row.organization_id === scope.organization && row.batch_id === selected.batch_id
    && row.association_id === selected.association_id && row.revision === selected.revision)
}

export function ContactArticleDetails({ scope, contact, close, restoreFocus }: { scope: ApiScope; contact: Contact; close: () => void; restoreFocus: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const container = useRef<HTMLElement>(null)
  const restore = useRef(restoreFocus); restore.current = restoreFocus
  useLayoutEffect(() => {
    if (!scope.closed) heading.current?.focus()
    return () => {
      if (!scope.closed && container.current?.contains(document.activeElement)) restore.current()
    }
  }, [scope])
  return <section ref={container} id="contact-article-details" aria-label="Article details">
    <h4 ref={heading} tabIndex={-1}>Article details for the selected contact</h4>
    <p>Retained article facts are read separately under current authorization. They do not change the selected contact or its review state.</p>
    <button type="button" onClick={close}>Close article details</button>
    <CurrentArticleMetadata scope={scope} batch={contact.batch_id} />
  </section>
}
