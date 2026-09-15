import type { Policy } from '../../api/types'
import { nativePolicyByTag } from '../policies/catalog'
import type { MatrixResource } from './resources'

const PRIVATE_VISIBILITY_NATIVE_IDS = new Set(['visible_only', 'private_space', 'staff_only'])

/**
 * A resource is a "private zone" for filtering purposes when a persisted DRAFT/ACTIVE Policy
 * whose native intention is an inclusion-style visibility whitelist targets it directly, or
 * targets its parent category. Derived entirely from already-fetched Policy data (`catalog.ts`
 * categorisation) -- no independent conflict/permission computation.
 */
export function computePrivateResourceIds(policies: readonly Policy[], resources: readonly MatrixResource[]): Set<string> {
  const direct = new Set<string>()
  for (const policy of policies) {
    if (policy.lifecycle_state !== 'DRAFT' && policy.lifecycle_state !== 'ACTIVE') continue
    const native = nativePolicyByTag(policy)
    if (native && PRIVATE_VISIBILITY_NATIVE_IDS.has(native.id) && policy.scope_id) direct.add(policy.scope_id)
  }
  const result = new Set(direct)
  for (const resource of resources) {
    if (resource.categoryId && direct.has(resource.categoryId)) result.add(resource.id)
  }
  return result
}
