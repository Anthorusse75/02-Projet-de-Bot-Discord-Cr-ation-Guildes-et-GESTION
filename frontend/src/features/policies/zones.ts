import { useQueryClient } from '@tanstack/react-query'
import type { DiscordSnowflake } from '../../shared/discord-id'
import { apiRequest } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { LogicalGroup, LogicalGroupResource } from '../../api/types'
import type { PolicyTarget } from './catalog'

// "Zone publique + espace staff associé" (REQ-AP-ZONE-001/002/003) is not a
// new Discord structure: DID never creates a fake sub-category. It is a
// pairing of two ALREADY EXISTING categories/channels, recorded with the
// existing Stage04 logical_groups primitive (semantic_role is a free-form
// tag on a group resource, already supported by the backend contract) so
// the UI can show "these two belong together" without inventing a second
// grouping mechanism or a real Discord relationship that doesn't exist.
export const PUBLIC_ZONE_SEMANTIC_ROLE = 'did-zone-public'
export const STAFF_ZONE_SEMANTIC_ROLE = 'did-zone-staff'

export type PairedZone = {
  group: LogicalGroup
  publicResource: LogicalGroupResource
  staffResource: LogicalGroupResource
}

function resourceId(resource: LogicalGroupResource): string | null {
  return resource.discord_channel_id ?? resource.discord_role_id ?? null
}

export function findPairedZones(groups: readonly LogicalGroup[]): PairedZone[] {
  const result: PairedZone[] = []
  for (const group of groups) {
    const publicResource = group.resources?.find((resource) => resource.semantic_role === PUBLIC_ZONE_SEMANTIC_ROLE)
    const staffResource = group.resources?.find((resource) => resource.semantic_role === STAFF_ZONE_SEMANTIC_ROLE)
    if (publicResource && staffResource) result.push({ group, publicResource, staffResource })
  }
  return result
}

export function zoneResourceLabel(resource: LogicalGroupResource | undefined, targets: readonly PolicyTarget[]): string | null {
  if (!resource) return null
  const id = resourceId(resource)
  if (id === null) return null
  const target = targets.find((item) => item.scopeId === id)
  return target?.label ?? id
}

export function slugifyZoneName(name: string): string {
  const base = name
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const suffix = crypto.randomUUID().slice(0, 8)
  return `${base || 'zone'}-${suffix}`.slice(0, 128)
}

export function useCreatePairedZone(u: DiscordSnowflake, g: DiscordSnowflake) {
  const queryClient = useQueryClient()
  return async function create(name: string, publicTarget: PolicyTarget, staffTarget: PolicyTarget): Promise<void> {
    if (!publicTarget.scopeId || !staffTarget.scopeId) throw new Error('zone targets must be real resources')
    const resourceType = (target: PolicyTarget): 'CATEGORY' | 'CHANNEL' => (target.scopeType === 'CATEGORY' ? 'CATEGORY' : 'CHANNEL')
    await apiRequest(`/api/v1/guilds/${g}/logical-groups`, {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: {
        name,
        slug: slugifyZoneName(name),
        description: null,
        metadata: { kind: 'public-staff-zone' },
        resources: [
          { resource_type: resourceType(publicTarget), discord_resource_id: publicTarget.scopeId, semantic_role: PUBLIC_ZONE_SEMANTIC_ROLE },
          { resource_type: resourceType(staffTarget), discord_resource_id: staffTarget.scopeId, semantic_role: STAFF_ZONE_SEMANTIC_ROLE },
        ],
      },
    })
    await queryClient.invalidateQueries({ queryKey: queryKeys.tenant(u, g, 'logical-groups') })
  }
}
