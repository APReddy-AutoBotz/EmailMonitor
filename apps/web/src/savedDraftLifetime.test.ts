import viewSource from './views.tsx?raw'
import ts from 'typescript'
import { expect, it } from 'vitest'

it('keeps saved-plan state outside the job-loading child lifetime', () => {
  const source = ts.createSourceFile('views.tsx', viewSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let count = 0
  function walk(node: ts.Node, loadingAncestor: boolean) {
    const loading = loadingAncestor || (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'Load')
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(source) === 'SavedDraft') {
      count++
      expect(loading, 'automatic action refresh removes Load children and their hook state').toBe(false)
    }
    ts.forEachChild(node, child => walk(child, loading))
  }
  walk(source, false)
  expect(count).toBe(1)
})
