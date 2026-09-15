import type { TFunction } from 'i18next'
import { ApiError } from '../../api/client'

export function apiProblem(error: unknown, t: TFunction): string {
  if (error instanceof ApiError && error.status === 403) return t('policies.error.denied')
  if (error instanceof ApiError && error.status === 409) return t('policies.error.conflict')
  return t('errors.generic', { requestId: error instanceof ApiError ? error.requestId : 'unknown' })
}
