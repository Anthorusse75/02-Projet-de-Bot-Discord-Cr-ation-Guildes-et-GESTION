import { useEffect, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { WizardStep } from './reducer'

export interface WizardShellProps<TAnswers> {
  steps: readonly WizardStep<TAnswers>[]
  stepIndex: number
  furthestIndex: number
  canGoNext: boolean
  canGoBack: boolean
  busy?: boolean
  nextLabelKey: string
  onGoToStep: (index: number) => void
  onBack: () => void
  onNext: () => void
  onCancel: () => void
  cancelLabelKey?: string
  children: ReactNode
}

/**
 * Generic step shell: progress nav (only completed/current steps are reachable), a focused
 * heading on every step change (REQ-WIZ-014), and previous/next/cancel controls. Never touches
 * Discord or any backend itself — all mutation-adjacent calls live in the caller's step content.
 */
export function WizardShell<TAnswers>({
  steps, stepIndex, furthestIndex, canGoNext, canGoBack, busy, nextLabelKey,
  onGoToStep, onBack, onNext, onCancel, cancelLabelKey, children,
}: WizardShellProps<TAnswers>) {
  const { t } = useTranslation()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const step = steps[stepIndex]

  useEffect(() => {
    headingRef.current?.focus()
  }, [stepIndex])

  return (
    <section className="wizard-shell">
      <nav className="wizard-progress" aria-label={t('wizard.progress')}>
        <ol>
          {steps.map((item, index) => {
            const reachable = index <= furthestIndex
            const isCurrent = index === stepIndex
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`wizard-progress-step ${isCurrent ? 'current' : ''} ${index < stepIndex ? 'done' : ''}`}
                  aria-current={isCurrent ? 'step' : undefined}
                  disabled={!reachable}
                  onClick={() => reachable && onGoToStep(index)}
                >
                  <span className="wizard-progress-index">{index + 1}</span>
                  <span>{t(item.titleKey)}</span>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>

      <div className="wizard-step-content">
        <h2 ref={headingRef} tabIndex={-1}>{step ? t(step.titleKey) : ''}</h2>
        {children}
      </div>

      <div className="button-row wizard-controls">
        <button type="button" className="button quiet" onClick={onCancel}>{t(cancelLabelKey ?? 'wizard.cancel')}</button>
        <div className="wizard-controls-nav">
          <button type="button" className="button quiet" disabled={!canGoBack || busy} onClick={onBack}>{t('wizard.back')}</button>
          <button type="button" className="button primary" disabled={!canGoNext || busy} onClick={onNext}>{t(nextLabelKey)}</button>
        </div>
      </div>
    </section>
  )
}
