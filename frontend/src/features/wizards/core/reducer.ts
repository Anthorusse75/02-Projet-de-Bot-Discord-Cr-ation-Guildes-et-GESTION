export interface WizardStep<TAnswers> {
  id: string
  titleKey: string
  isComplete: (answers: TAnswers) => boolean
}

export interface WizardState<TAnswers> {
  stepIndex: number
  furthestIndex: number
  answers: TAnswers
}

export type WizardAction<TAnswers> =
  | { type: 'UPDATE'; patch: Partial<TAnswers>; resetKeys: (keyof TAnswers)[] | undefined }
  | { type: 'NEXT' }
  | { type: 'BACK' }
  | { type: 'GOTO'; index: number }
  | { type: 'RESET' }

export function initialWizardState<TAnswers>(initialAnswers: TAnswers): WizardState<TAnswers> {
  return { stepIndex: 0, furthestIndex: 0, answers: initialAnswers }
}

/**
 * A step's own answer never needs explicit invalidation (it just changed). `resetKeys` names
 * the OTHER answer keys — belonging to later steps — that become stale and must revert to their
 * initial value (REQ-WIZ-003). Any step at or after the first reset key is walked back to
 * "not yet confirmed" by clamping furthestIndex to the current position.
 */
export function createWizardReducer<TAnswers>(steps: readonly WizardStep<TAnswers>[], initialAnswers: TAnswers) {
  return function wizardReducer(state: WizardState<TAnswers>, action: WizardAction<TAnswers>): WizardState<TAnswers> {
    switch (action.type) {
      case 'UPDATE': {
        const answers: TAnswers = { ...state.answers, ...action.patch }
        const resetKeys = action.resetKeys ?? []
        for (const key of resetKeys) answers[key] = initialAnswers[key]
        const furthestIndex = resetKeys.length > 0 ? Math.min(state.furthestIndex, state.stepIndex) : state.furthestIndex
        return { ...state, answers, furthestIndex }
      }
      case 'NEXT': {
        const current = steps[state.stepIndex]
        if (!current || !current.isComplete(state.answers)) return state
        const stepIndex = Math.min(steps.length - 1, state.stepIndex + 1)
        return { ...state, stepIndex, furthestIndex: Math.max(state.furthestIndex, stepIndex) }
      }
      case 'BACK':
        return { ...state, stepIndex: Math.max(0, state.stepIndex - 1) }
      case 'GOTO':
        if (action.index < 0 || action.index > state.furthestIndex) return state
        return { ...state, stepIndex: action.index }
      case 'RESET':
        return initialWizardState(initialAnswers)
      default:
        return state
    }
  }
}
