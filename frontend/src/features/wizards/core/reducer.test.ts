import { createWizardReducer, initialWizardState, type WizardStep } from './reducer'

interface Answers {
  target: string | null
  roles: string[]
  preview: string | null
}

const initialAnswers: Answers = { target: null, roles: [], preview: null }

const steps: WizardStep<Answers>[] = [
  { id: 'target', titleKey: 'step.target', isComplete: (a) => a.target !== null },
  { id: 'roles', titleKey: 'step.roles', isComplete: (a) => a.roles.length > 0 },
  { id: 'preview', titleKey: 'step.preview', isComplete: (a) => a.preview !== null },
]

function reducer() {
  return createWizardReducer(steps, initialAnswers)
}

describe('wizard reducer navigation', () => {
  it('does not advance past an incomplete step', () => {
    const state = initialWizardState(initialAnswers)
    const next = reducer()(state, { type: 'NEXT' })
    expect(next.stepIndex).toBe(0)
  })

  it('advances forward once the current step is complete, and tracks the furthest reached step', () => {
    let state = initialWizardState(initialAnswers)
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'GUILD:*' }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    expect(state.stepIndex).toBe(1)
    expect(state.furthestIndex).toBe(1)
  })

  it('goes back without losing furthestIndex', () => {
    let state = initialWizardState(initialAnswers)
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'GUILD:*' }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    state = reducer()(state, { type: 'BACK' })
    expect(state.stepIndex).toBe(0)
    expect(state.furthestIndex).toBe(1)
  })

  it('goToStep only reaches steps within furthestIndex', () => {
    let state = initialWizardState(initialAnswers)
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'GUILD:*' }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    const blocked = reducer()(state, { type: 'GOTO', index: 2 })
    expect(blocked.stepIndex).toBe(1)
    const allowed = reducer()(state, { type: 'GOTO', index: 0 })
    expect(allowed.stepIndex).toBe(0)
  })
})

describe('wizard reducer dependent-step invalidation (REQ-WIZ-003)', () => {
  it('changing an earlier answer clears the dependent answers named in resetKeys', () => {
    let state = initialWizardState(initialAnswers)
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'GUILD:*' }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    state = reducer()(state, { type: 'UPDATE', patch: { roles: ['role-1'] }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    state = reducer()(state, { type: 'UPDATE', patch: { preview: 'computed-preview' }, resetKeys: undefined })
    expect(state.answers.preview).toBe('computed-preview')

    // Going back and changing the target must invalidate the stale preview instead of leaving
    // it visible for a target it no longer describes.
    state = reducer()(state, { type: 'GOTO', index: 0 })
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'CATEGORY:1' }, resetKeys: ['roles', 'preview'] })
    expect(state.answers.target).toBe('CATEGORY:1')
    expect(state.answers.roles).toEqual([])
    expect(state.answers.preview).toBeNull()
  })

  it('clamps furthestIndex back so invalidated later steps must be re-confirmed', () => {
    let state = initialWizardState(initialAnswers)
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'GUILD:*' }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    state = reducer()(state, { type: 'UPDATE', patch: { roles: ['role-1'] }, resetKeys: undefined })
    state = reducer()(state, { type: 'NEXT' })
    expect(state.furthestIndex).toBe(2)

    state = reducer()(state, { type: 'GOTO', index: 0 })
    state = reducer()(state, { type: 'UPDATE', patch: { target: 'CATEGORY:1' }, resetKeys: ['roles', 'preview'] })
    expect(state.furthestIndex).toBe(0)
    const jumpToPreview = reducer()(state, { type: 'GOTO', index: 2 })
    expect(jumpToPreview.stepIndex).toBe(0)
  })
})
