import viewSource from './views.tsx?raw'
import ts from 'typescript'
import { expect, it } from 'vitest'

it('keeps saved-plan and deletion-receipt state outside the job-loading child lifetime', () => {
  const source = ts.createSourceFile('views.tsx', viewSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const counts = { SavedDraft: 0, JobDeletion: 0 }
  function walk(node: ts.Node, loadingAncestor: boolean) {
    const loading = loadingAncestor || (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'Load')
    if (ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(source)
      if (tag === 'SavedDraft' || tag === 'JobDeletion') {
        counts[tag]++
        expect(loading, 'automatic action refresh removes Load children and their hook state').toBe(false)
        const attributes = node.attributes.getText(source)
        expect(attributes).toContain('context={c}')
        expect(attributes).toContain('resource={job}')
        expect(attributes).toContain('id={id}')
        expect(attributes).toContain('c.scope.organization')
      }
    }
    ts.forEachChild(node, child => walk(child, loading))
  }
  walk(source, false)
  expect(counts).toEqual({ SavedDraft: 1, JobDeletion: 1 })
})
