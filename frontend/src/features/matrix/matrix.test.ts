import type { AccessMatrixCell } from '../../api/types'
import { nativePolicies } from '../policies/catalog'
import { analyzeBulkCompatibility, toggleResourceSelection } from './bulk'
import { matchesFilter, synthesisLabelKey } from './cells'
import type { MatrixResource } from './resources'

function cell(values: Partial<AccessMatrixCell> = {}): AccessMatrixCell {
  return {
    role_id: '100', resource_id: '200', synthesis: 'VIEW', permission_status: 'COMPLETE',
    policy_outcome: 'CAN', conflict: false, exception: false, inherited: false,
    contributing_policy_ids: [], conflict_policy_ids: [], incomplete_reasons: [],
    role_known: true, resource_known: true, ...values,
  } as AccessMatrixCell
}

describe('Phase 4 access matrix presentation', () => {
  it('maps canonical synthesis values to human label keys, including UNKNOWN', () => {
    expect(synthesisLabelKey('NONE')).toBe('matrix.access.none')
    expect(synthesisLabelKey('VIEW')).toBe('policies.access.VIEW')
    expect(synthesisLabelKey('WRITE')).toBe('policies.access.WRITE')
    expect(synthesisLabelKey('MANAGE')).toBe('policies.access.MANAGE')
    expect(synthesisLabelKey('UNKNOWN')).toBe('matrix.access.unknown')
  })

  it('filters only on backend conflict/exception flags and known private resources', () => {
    const conflict = cell({ conflict: true })
    const exception = cell({ exception: true })
    expect(matchesFilter(conflict, 'CONFLICTS', new Set())).toBe(true)
    expect(matchesFilter(conflict, 'EXCEPTIONS', new Set())).toBe(false)
    expect(matchesFilter(exception, 'EXCEPTIONS', new Set())).toBe(true)
    expect(matchesFilter(cell(), 'PRIVATE', new Set(['200']))).toBe(true)
  })

  it('explicitly excludes an incompatible voice resource with its reason', () => {
    const resources: MatrixResource[] = [
      { id: '200', kind: 'TEXT_CHANNEL', label: 'general', categoryId: null },
      { id: '201', kind: 'VOICE_CHANNEL', label: 'Lounge', categoryId: null },
    ]
    const visibleOnly = nativePolicies.find((policy) => policy.id === 'visible_only')
    expect(visibleOnly).toBeDefined()
    if (!visibleOnly) throw new Error('visible_only fixture missing')
    const result = analyzeBulkCompatibility(visibleOnly, resources)
    expect(result.compatible.map((resource) => resource.id)).toEqual(['200'])
    expect(result.excluded).toEqual([{ resource: resources[1], reasonKey: 'matrix.bulk.reason.voice' }])
  })

  it('adds and removes multiple resources without silently replacing the selection', () => {
    expect(toggleResourceSelection(toggleResourceSelection([], '200'), '201')).toEqual(['200', '201'])
    expect(toggleResourceSelection(['200', '201'], '200')).toEqual(['201'])
  })
})
