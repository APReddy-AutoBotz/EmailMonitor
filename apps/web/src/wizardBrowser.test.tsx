import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiScope } from './client'
import type { Context } from './ui'
import { Wizard } from './views'
import { SourcePlanSummary } from './sourcePlanSummary'

// Exercise real form handlers without adding a DOM/browser dependency.
const hooks = vi.hoisted(() => ({ values: [] as unknown[], index: 0 }))
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial?: unknown) => {
    const index = hooks.index++
    if (!(index in hooks.values)) hooks.values[index] = initial
    return [hooks.values[index], (value: unknown) => { hooks.values[index] = value }]
  },
  useRef: (initial: unknown) => {
    const index = hooks.index++
    if (!(index in hooks.values)) hooks.values[index] = { current: initial }
    return hooks.values[index]
  },
}))
vi.mock('./ui', async importOriginal => ({
  ...await importOriginal<typeof import('./ui')>(),
  useResource: (_: unknown, path: string) => ({ loading: false, data: path === '/sources' ? [{ source_id: 'synthetic-publisher', enabled: true, execution_mode: 'fixture' }] : [{ state: 'approved', valid_until: '2099-01-01T00:00:00Z', version: 1 }] }),
}))
type Props = { children?: ReactNode; type?: string; checked?: boolean; disabled?: boolean; onClick?: () => void; 'aria-label'?: string; onChange?: (event: { target: { checked: boolean; value?: string } }) => void }
function elements(node: ReactNode): ReactElement<Props>[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Props>(node)) return []
  return [node, ...elements(node.props.children)]
}
function setup(canAcquire = true, option = 'allow_browser') {
  const scope = new ApiScope('00000000-0000-0000-0000-000000000001', 'test-only')
  const job = { id: '00000000-0000-0000-0000-000000000002', state: 'draft', row_version: 1 }
  const write = vi.spyOn(scope, 'write').mockImplementation(async path => path === '/jobs' ? job : { classification: 'article' })
  vi.spyOn(scope, 'request').mockResolvedValue(job)
  let pending: Promise<unknown> = Promise.resolve()
  const context: Context = { scope, revision: 0, refresh: vi.fn(), confirm: vi.fn(), identity: 'test', zone: 'UTC', openJob: vi.fn(), can: () => canAcquire,
    act: vi.fn((_label, work) => { pending = work(); return pending.then(() => undefined) }),
  }
  const render = () => { hooks.index = 0; return Wizard({ context }) }
  const checkbox = () => elements(render()).filter(element => element.type === 'input' && element.props.type === 'checkbox' && element.props.onChange && element.props.checked !== undefined)[option === 'allow_browser' ? 0 : 1]!
  const toggle = (checked: boolean) => { checkbox().props.onChange!({ target: { checked } }); render() }
  const submit = () => { render().props.onSubmit({ preventDefault: vi.fn() }); return pending }
  const hasPlan = () => elements(render()).some(element => element.props['aria-label'] === 'Server source plan')
  const launchDisabled = () => elements(render()).find(element => element.type === 'button' && element.props.children === 'Launch extraction')!.props.disabled
  const launch = () => { elements(render()).find(element => element.type === 'button' && element.props.children === 'Launch extraction')!.props.onClick!(); return pending }
  const chooseSource = (value: string) => {
    elements(render()).find(element => element.type === 'select')!.props.onChange!({ target: { checked: false, value } }); render()
  }
  const changeDate = (label: string, value: string) => {
    elements(render()).find(element => element.props['aria-label'] === label && element.props.onChange)!.props.onChange!({ target: { checked: false, value } }); render()
  }
  const requestReuse = (checked: boolean) => {
    elements(render()).find(element => element.props['aria-label'] === 'Request retained observation reuse')!.props.onChange!({ target: { checked } }); render()
  }
  return { checkbox, toggle, submit, hasPlan, launch, launchDisabled, write, context, chooseSource, changeDate, requestReuse, render }
}
beforeEach(() => { hooks.values = []; hooks.index = 0; vi.restoreAllMocks() })

describe('repeated plan requests', () => {
  it('keeps malformed or unpersisted supported-looking plans from enabling launch', async () => {
    const form = setup()
    for (const response of [{ plan: { classification: ['article'] } }, { plan: null, classification: 'article' }, { plan: { classification: 'article' }, persisted: false }]) {
      form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : response)
      await form.submit()
      expect(form.launchDisabled()).toBe(true)
    }
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
  it('opens the returned draft without starting extraction', async () => {
    const form = setup()
    await form.submit()
    elements(form.render()).find(element => element.type === 'button' && element.props.children === 'Open draft job')!.props.onClick!()
    expect(form.context.openJob).toHaveBeenCalledWith('00000000-0000-0000-0000-000000000002')
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
  it('clears the previous plan before a repeat request that fails', async () => {
    const form = setup()
    await form.submit()
    expect(form.hasPlan()).toBe(true)
    form.write.mockImplementation(async path => {
      if (path === '/jobs') return { id: '00000000-0000-0000-0000-000000000002' }
      throw new Error('Synthetic plan refusal')
    })
    await expect(form.submit()).rejects.toThrow('Synthetic plan refusal')
    expect(form.hasPlan()).toBe(false)
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
    const creates = form.write.mock.calls.filter(([path]) => path === '/jobs')
    expect(creates[0][3]).toBe(creates[1][3])
  })
  it('rejects a late earlier response even when repeated inputs are identical', async () => {
    const form = setup()
    let release!: (value: { classification: string }) => void
    let plans = 0
    form.write.mockImplementation(async path => {
      if (path === '/jobs') return { id: '00000000-0000-0000-0000-000000000002' }
      plans += 1
      return plans === 1 ? new Promise(resolve => { release = resolve }) : { classification: 'unsupported' }
    })
    const first = form.submit()
    await vi.waitFor(() => expect(release).toBeTypeOf('function'))
    await form.submit()
    expect(form.hasPlan()).toBe(true)
    expect(form.launchDisabled()).toBe(true)
    release({ classification: 'article' })
    await first
    expect(form.launchDisabled()).toBe(true)
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
})

describe('retained reuse request is explicit and fail-closed', () => {
  it('omits reuse by default and carries an explicit cutoff without silently launching', async () => {
    const form = setup()
    await form.submit()
    const first = form.write.mock.calls.find(([path]) => path === '/jobs')![1] as Record<string, unknown>
    expect(first).not.toHaveProperty('reuse')
    form.requestReuse(true)
    expect(form.hasPlan()).toBe(false)
    form.changeDate('Reuse freshness cutoff UTC', '2026-10-01T13:00')
    form.write.mockImplementation(async path => { if (path === '/jobs') throw new Error('Retained observation reuse is not yet available'); return {} })
    await expect(form.submit()).rejects.toThrow('Retained observation reuse is not yet available')
    const creates = form.write.mock.calls.filter(([path]) => path === '/jobs')
    expect(creates[1][1]).toMatchObject({ reuse: { mode: 'verified_retained', fresh_since: '2026-10-01T13:00:00Z' } })
    expect(creates[1][3]).not.toBe(creates[0][3])
    expect(form.hasPlan()).toBe(false)
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
  it('rejects a cutoff-free explicit request before creating a job', async () => {
    const form = setup()
    form.requestReuse(true)
    await expect(form.submit()).rejects.toThrow('Choose a complete UTC freshness cutoff')
    expect(form.write).not.toHaveBeenCalled()
  })
  it('rejects a late fresh plan after reuse is selected', async () => {
    const form = setup()
    let release!: (value: { classification: string }) => void
    form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : new Promise(resolve => { release = resolve }))
    const pending = form.submit()
    await vi.waitFor(() => expect(release).toBeTypeOf('function'))
    form.requestReuse(true)
    release({ classification: 'article' }); await pending
    expect(form.hasPlan()).toBe(false)
    expect(form.context.openJob).not.toHaveBeenCalled()
  })
})

describe.each(['allow_browser', 'allow_pdf'])('explicit synthetic %s job opt-in', option => {
  it('starts unchecked and sends false by default, then true only after opt-in', async () => {
    const form = setup(true, option)
    expect(form.checkbox().props.checked).toBe(false)
    await form.submit()
    expect(form.write.mock.calls[0][1]).toMatchObject({ options: { allow_browser: false, allow_pdf: false, allow_ocr: false, allow_wider_web: false } })
    const firstKey = form.write.mock.calls[0][3]
    form.toggle(true)
    await form.submit()
    const creates = form.write.mock.calls.filter(([path]) => path === '/jobs')
    expect(creates[1][1]).toMatchObject({ options: { [option]: true, [option === 'allow_pdf' ? 'allow_browser' : 'allow_pdf']: false } })
    expect(creates[1][3]).not.toBe(firstKey)
  })
  it('clears an existing launch plan when toggled on or off', async () => {
    const form = setup(true, option)
    await form.submit(); expect(form.hasPlan()).toBe(true)
    form.toggle(true); expect(form.hasPlan()).toBe(false)
    await form.submit(); expect(form.hasPlan()).toBe(true)
    form.toggle(false); expect(form.hasPlan()).toBe(false)
  })
  it('rejects a late plan response for the previous opt-in value', async () => {
    const form = setup(true, option)
    let release!: (value: { classification: string }) => void
    form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : new Promise(resolve => { release = resolve }))
    const submitted = form.submit()
    await vi.waitFor(() => expect(release).toBeTypeOf('function'))
    form.toggle(true)
    release({ classification: 'article' })
    await submitted
    expect(form.hasPlan()).toBe(false)
    expect(form.context.openJob).not.toHaveBeenCalled()
  })
  it('does not launch the previous plan if opt-in changes during the launch revision read', async () => {
    const form = setup(true, option)
    await form.submit()
    let release!: (value: { row_version: number }) => void
    vi.mocked(form.context.scope.request).mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const launching = form.launch()
    form.toggle(true)
    release({ row_version: 2 })
    await launching
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
    expect(form.context.openJob).not.toHaveBeenCalled()
  })
  it('keeps the opt-in disabled for roles without acquisition authority', () => {
    const form = setup(false, option)
    expect(form.checkbox().props.disabled).toBe(true)
    expect(form.checkbox().props.checked).toBe(false)
    expect(form.write).not.toHaveBeenCalled()
  })
})

describe('registered source plan ownership', () => {
  it('sends selected identity, refuses cleared input and invalidates its plan', async () => {
    const form = setup()
    await form.submit()
    expect(form.write.mock.calls[0][1]).toMatchObject({ input: { source_id: 'synthetic-publisher' } })
    expect(form.hasPlan()).toBe(true)
    form.chooseSource('')
    expect(form.hasPlan()).toBe(false)
    await expect(form.submit()).rejects.toThrow('Select the existing available fixture source')
    form.chooseSource('elsevier_sciencedirect_v2')
    await expect(form.submit()).rejects.toThrow('Select the existing available fixture source')
    expect(form.write.mock.calls.filter(([path]) => path === '/jobs')).toHaveLength(1)
  })
  it('refuses late source A response after clear and return to A', async () => {
    const form = setup()
    let release!: (value: { classification: string }) => void
    form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : new Promise(resolve => { release = resolve }))
    const pending = form.submit()
    await vi.waitFor(() => expect(release).toBeTypeOf('function'))
    form.chooseSource(''); form.chooseSource('synthetic-publisher')
    release({ classification: 'article' }); await pending
    expect(form.hasPlan()).toBe(false)
    expect(form.context.openJob).not.toHaveBeenCalled()
  })
  it('cannot launch when source changes during the revision read', async () => {
    const form = setup(); await form.submit()
    let release!: (value: { row_version: number }) => void
    vi.mocked(form.context.scope.request).mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const pending = form.launch()
    form.chooseSource(''); form.chooseSource('synthetic-publisher')
    release({ row_version: 2 }); await pending
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
})

it('does not navigate from a completed launch response after source or session invalidation', async () => {
  const form = setup(); await form.submit()
  let release!: () => void
  form.write.mockImplementationOnce(() => new Promise(resolve => { release = () => resolve({}) }))
  const pending = form.launch()
  await vi.waitFor(() => expect(release).toBeTypeOf('function'))
  form.chooseSource(''); form.context.scope.close()
  release(); await pending
  expect(form.context.openJob).not.toHaveBeenCalled()
})


describe('publication date request ownership', () => {
  it('connects the returned draft and refusal to the summary and clears it when input changes', async () => {
    const form = setup()
    const request = { input: { type: 'keyword', source_id: 'synthetic-publisher' }, filters: { publication_date_type: 'online', publication_from: '2026-01-15' } }
    vi.mocked(form.context.scope.request).mockResolvedValue({ id: '00000000-0000-0000-0000-000000000002', state: 'draft', row_version: 1, request })
    const refusal = { plan: { classification: 'unsupported', reason: 'fixture_filters_unavailable' }, persisted: false }
    form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : refusal)
    form.changeDate('Publication date from', '2026-01-15')
    form.changeDate('Publication date type', 'online')
    await form.submit()
    const summary = elements(form.render()).find(element => element.type === SourcePlanSummary)
    expect(summary?.props).toMatchObject({ plan: refusal, job: { request } })
    expect(form.launchDisabled()).toBe(true)
    form.changeDate('Publication date type', 'issue')
    expect(form.hasPlan()).toBe(false)
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
  it('preserves the explicit date type, clears old plans and changes request identity', async () => {
    const form = setup()
    await form.submit(); expect(form.hasPlan()).toBe(true)
    const firstKey = form.write.mock.calls[0][3]
    form.changeDate('Publication date from', '2026-01-15')
    expect(form.hasPlan()).toBe(false)
    await expect(form.submit()).rejects.toThrow('Choose a publication date type')
    form.changeDate('Publication date type', 'online')
    await form.submit()
    const creates = form.write.mock.calls.filter(([path]) => path === '/jobs')
    expect(creates[1][1]).toMatchObject({ filters: { publication_date_type: 'online', publication_from: '2026-01-15' } })
    expect(creates[1][3]).not.toBe(firstKey)
    form.changeDate('Publication date type', 'issue')
    expect(form.hasPlan()).toBe(false)
  })
  it('keeps launch disabled when the server refuses the selected filter', async () => {
    const form = setup()
    form.changeDate('Publication date from', '2026-01-15')
    form.changeDate('Publication date type', 'published')
    form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : { plan: { classification: 'unsupported', reason: 'fixture_filters_unavailable' } })
    await form.submit()
    expect(form.hasPlan()).toBe(true)
    expect(form.launchDisabled()).toBe(true)
    expect(form.write.mock.calls.some(([path]) => path.endsWith('/start'))).toBe(false)
  })
  it('cannot restore a late plan after a date selection changes', async () => {
    const form = setup()
    let release!: (value: { classification: string }) => void
    form.write.mockImplementation(async path => path === '/jobs' ? { id: '00000000-0000-0000-0000-000000000002' } : new Promise(resolve => { release = resolve }))
    const pending = form.submit()
    await vi.waitFor(() => expect(release).toBeTypeOf('function'))
    form.changeDate('Publication date from', '2026-01-15')
    release({ classification: 'article' }); await pending
    expect(form.hasPlan()).toBe(false)
    expect(form.context.openJob).not.toHaveBeenCalled()
  })
})
