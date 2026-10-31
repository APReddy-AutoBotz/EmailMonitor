/** Preserve requested text exactly; source capability and authorization are server decisions. */
export function sourceSearchFilters(journal: string, articleType: string): { journal?: string; article_types?: string[] } {
  const valid = (value: string, maximum: number) => value.length <= maximum && !!value.trim() && !/[\u0000-\u001f\u007f]/.test(value)
  if (journal && !valid(journal, 300)) throw new Error('Enter a nonblank journal without control characters')
  if (articleType && !valid(articleType, 100)) throw new Error('Enter a nonblank article type without control characters')
  return { ...(journal ? { journal } : {}), ...(articleType ? { article_types: [articleType] } : {}) }
}
