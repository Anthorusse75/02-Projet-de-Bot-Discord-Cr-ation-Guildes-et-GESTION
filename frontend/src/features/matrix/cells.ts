import type { AccessMatrixCell, AccessSynthesis } from '../../api/types'

// Must stay <= MAX_MATRIX_ROLES / MAX_MATRIX_RESOURCES in backend/src/did/api/policies.py.
export const MAX_MATRIX_ROLES = 50
export const MAX_MATRIX_RESOURCES = 150

const SYNTHESIS_LABEL_KEYS: Record<AccessSynthesis, string> = {
  UNKNOWN: 'matrix.access.unknown',
  NONE: 'matrix.access.none',
  VIEW: 'policies.access.VIEW',
  WRITE: 'policies.access.WRITE',
  MANAGE: 'policies.access.MANAGE',
  CONNECT: 'policies.access.CONNECT',
  SPEAK: 'policies.access.SPEAK',
}

export function synthesisLabelKey(synthesis: AccessSynthesis): string {
  return SYNTHESIS_LABEL_KEYS[synthesis]
}

export function synthesisTone(synthesis: AccessSynthesis): 'neutral' | 'ok' {
  return synthesis === 'NONE' || synthesis === 'UNKNOWN' ? 'neutral' : 'ok'
}

export function cellKey(roleId: string, resourceId: string): string {
  return `${roleId}:${resourceId}`
}

export function cellIsUnknown(cell: AccessMatrixCell): boolean {
  return !cell.role_known || !cell.resource_known || cell.permission_status !== 'COMPLETE' || cell.synthesis === 'UNKNOWN'
}

export type MatrixFilter = 'ALL' | 'CONFLICTS' | 'EXCEPTIONS' | 'PRIVATE'

/**
 * Pure filter over an already-resolved cell (REQ-AP-MAT-005). Never recomputes conflict/exception
 * itself -- those booleans come straight from the batch resolution.
 */
export function matchesFilter(cell: AccessMatrixCell, filter: MatrixFilter, privateResourceIds: ReadonlySet<string>): boolean {
  if (filter === 'CONFLICTS') return cell.conflict
  if (filter === 'EXCEPTIONS') return cell.exception
  if (filter === 'PRIVATE') return privateResourceIds.has(cell.resource_id)
  return true
}
