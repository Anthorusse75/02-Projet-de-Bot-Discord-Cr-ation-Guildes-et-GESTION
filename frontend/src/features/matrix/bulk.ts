import type { PolicyPreview } from '../../api/types'
import type { NativePolicy, PolicyTargetKind } from '../policies/catalog'
import type { MatrixResource } from './resources'

export type BulkExclusion = { resource: MatrixResource; reasonKey: string }
export type BulkCompatibility = { compatible: MatrixResource[]; excluded: BulkExclusion[] }

function targetKind(resource: MatrixResource): PolicyTargetKind {
  return resource.kind
}

export function analyzeBulkCompatibility(policy: NativePolicy, resources: readonly MatrixResource[]): BulkCompatibility {
  const compatible: MatrixResource[] = []
  const excluded: BulkExclusion[] = []
  const selectedCategoryIds = new Set(resources.filter((resource) => resource.kind === 'CATEGORY').map((resource) => resource.id))
  for (const resource of resources) {
    if (resource.categoryId && selectedCategoryIds.has(resource.categoryId)) excluded.push({
      resource,
      reasonKey: 'matrix.bulk.reason.inheritedByCategory',
    })
    else if (policy.compatibility.includes(targetKind(resource))) compatible.push(resource)
    else excluded.push({
      resource,
      reasonKey: resource.kind === 'VOICE_CHANNEL' ? 'matrix.bulk.reason.voice' : 'matrix.bulk.reason.resourceType',
    })
  }
  return { compatible, excluded }
}

export function compatibleBulkPolicies(policies: readonly NativePolicy[], resources: readonly MatrixResource[]): NativePolicy[] {
  return policies.filter((policy) => policy.matrixCompatible !== false && analyzeBulkCompatibility(policy, resources).compatible.length > 0)
}

export function toggleResourceSelection(current: readonly string[], resourceId: string): string[] {
  return current.includes(resourceId)
    ? current.filter((id) => id !== resourceId)
    : [...current, resourceId]
}

export type BulkImpactSummary = {
  accuracy: 'EXACT' | 'BOUNDED' | 'INCOMPLETE'
  differences: number
  conflicts: number
  blocked: number
  unknown: number
}

export function summarizeBulkPreviews(previews: readonly PolicyPreview[]): BulkImpactSummary {
  const rank = { EXACT: 0, BOUNDED: 1, INCOMPLETE: 2 } as const
  const accuracy = previews.reduce<BulkImpactSummary['accuracy']>(
    (current, preview) => rank[preview.impact.accuracy] > rank[current] ? preview.impact.accuracy : current,
    'EXACT',
  )
  return {
    accuracy,
    differences: previews.reduce((total, preview) => total + preview.entries.filter((entry) => entry.access_change !== 'UNCHANGED').length, 0),
    conflicts: previews.reduce((total, preview) => total + preview.impact.conflicts, 0),
    blocked: previews.reduce((total, preview) => total + preview.entries.filter((entry) => entry.proposed.outcome === 'BLOCKED').length, 0),
    unknown: previews.reduce((total, preview) => total + preview.entries.filter((entry) => entry.proposed.outcome === 'UNKNOWN').length, 0),
  }
}
