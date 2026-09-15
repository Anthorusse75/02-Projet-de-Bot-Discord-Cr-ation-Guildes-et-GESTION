import { useMemo, useReducer } from 'react'
import { createWizardReducer, initialWizardState, type WizardStep } from './reducer'

export interface UseWizardResult<TAnswers> {
  steps: readonly WizardStep<TAnswers>[]
  stepIndex: number
  furthestIndex: number
  currentStep: WizardStep<TAnswers>
  answers: TAnswers
  canGoNext: boolean
  canGoBack: boolean
  goNext: () => void
  goBack: () => void
  goToStep: (index: number) => void
  updateAnswers: (patch: Partial<TAnswers>, resetKeys?: (keyof TAnswers)[] | undefined) => void
  reset: () => void
}

/**
 * Generic multi-step wizard primitive (REQ-WIZ-001..010, 013, 014). Holds only navigation +
 * answers state; every backend call (preview, draft creation, plan) stays in the caller's step
 * components so this core never grows a second resolution/plan engine.
 */
export function useWizard<TAnswers extends object>(
  steps: readonly WizardStep<TAnswers>[],
  initialAnswers: TAnswers,
): UseWizardResult<TAnswers> {
  const reducer = useMemo(() => createWizardReducer(steps, initialAnswers), [steps, initialAnswers])
  const [state, dispatch] = useReducer(reducer, initialAnswers, initialWizardState)
  // Callers always provide a non-empty steps array; the wizard has nowhere to go otherwise.
  const currentStep = (steps[state.stepIndex] ?? steps[0]) as WizardStep<TAnswers>

  return {
    steps,
    stepIndex: state.stepIndex,
    furthestIndex: state.furthestIndex,
    currentStep,
    answers: state.answers,
    canGoNext: currentStep.isComplete(state.answers),
    canGoBack: state.stepIndex > 0,
    goNext: () => dispatch({ type: 'NEXT' }),
    goBack: () => dispatch({ type: 'BACK' }),
    goToStep: (index) => dispatch({ type: 'GOTO', index }),
    updateAnswers: (patch, resetKeys) => dispatch({ type: 'UPDATE', patch, resetKeys }),
    reset: () => dispatch({ type: 'RESET' }),
  }
}
