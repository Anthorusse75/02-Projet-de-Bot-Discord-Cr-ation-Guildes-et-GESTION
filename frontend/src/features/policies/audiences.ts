import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { DiscordSnowflake } from '../../shared/discord-id'
import { apiRequest } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { tenantSignal } from '../../api/tenantLifecycle'
import type { Role, VisibilityScope } from '../../api/types'

// A "Named Audience" (Staff, Confirmed member, ...) is not a new persistence
// primitive: it reuses the existing, already tenant-safe/RLS/audited
// `visibility_scopes` + `scope_membership_rules` tables (Stage04). Staff uses
// the scope_type the domain already reserves for it; every other named
// audience (Confirmed member included) is a CUSTOM scope distinguished by a
// well-known scope_key, so no schema change was needed to add this one.
export const STAFF_SCOPE_KEY = 'staff'
export const CONFIRMED_MEMBER_SCOPE_KEY = 'confirmed_member'

export type NamedAudienceKind = 'STAFF' | 'CONFIRMED_MEMBER'

export type NamedAudience = {
  id: string
  name: string
  roleIds: readonly DiscordSnowflake[]
  version: number
}

function scopeKeyFor(kind: NamedAudienceKind): string {
  return kind === 'STAFF' ? STAFF_SCOPE_KEY : CONFIRMED_MEMBER_SCOPE_KEY
}

function scopeTypeFor(kind: NamedAudienceKind): 'STAFF' | 'CUSTOM' {
  return kind === 'STAFF' ? 'STAFF' : 'CUSTOM'
}

function toNamedAudience(scope: VisibilityScope): NamedAudience {
  const roleIds = scope.rules
    .filter((rule) => rule.rule_type === 'ANY_DISCORD_ROLE' || rule.rule_type === 'DISCORD_ROLE')
    .flatMap((rule) => rule.config.role_ids ?? [])
  return { id: scope.id, name: scope.name, roleIds: [...new Set(roleIds)] as DiscordSnowflake[], version: scope.version }
}

export function findNamedAudience(scopes: readonly VisibilityScope[], kind: NamedAudienceKind): NamedAudience | null {
  const scope = scopes.find((value) => value.scope_type === scopeTypeFor(kind) && value.scope_key === scopeKeyFor(kind))
  return scope ? toNamedAudience(scope) : null
}

export function useVisibilityScopes(u: DiscordSnowflake, g: DiscordSnowflake, enabled = true) {
  return useQuery({
    queryKey: queryKeys.tenant(u, g, 'visibility-scopes'),
    queryFn: () => apiRequest<{ guild_id: DiscordSnowflake; scopes: VisibilityScope[] }>(`/api/v1/guilds/${g}/visibility-scopes`, { signal: tenantSignal(g) }),
    enabled,
  })
}

export function useNamedAudience(u: DiscordSnowflake, g: DiscordSnowflake, kind: NamedAudienceKind, enabled = true) {
  const scopes = useVisibilityScopes(u, g, enabled)
  return { ...scopes, audience: scopes.data ? findNamedAudience(scopes.data.scopes, kind) : null }
}

export function useSaveNamedAudience(u: DiscordSnowflake, g: DiscordSnowflake) {
  const queryClient = useQueryClient()
  return async function save(kind: NamedAudienceKind, existing: VisibilityScope | null, name: string, roleIds: readonly string[]): Promise<void> {
    const rules = [{ rule_type: 'ANY_DISCORD_ROLE' as const, config: { role_ids: [...roleIds] }, priority: 0 }]
    if (existing) {
      await apiRequest(`/api/v1/guilds/${g}/visibility-scopes/${existing.id}`, {
        method: 'PATCH',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { name, config: existing.config, rules, explicit_member_ids: existing.explicit_member_ids },
      })
    } else {
      await apiRequest(`/api/v1/guilds/${g}/visibility-scopes`, {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { scope_type: scopeTypeFor(kind), scope_key: scopeKeyFor(kind), name, config: {}, rules, explicit_member_ids: [] },
      })
    }
    await queryClient.invalidateQueries({ queryKey: queryKeys.tenant(u, g, 'visibility-scopes') })
  }
}

// Heuristic name-based suggestion only -- REQ-AP-ZONE-010/011 forbid
// inferring "Staff" (or any other audience) silently from role names. The
// caller must present this as a proposal the admin explicitly confirms
// before it is ever persisted; it is never applied on its own.
const STAFF_NAME_HINTS = ['admin', 'administrateur', 'moderat', 'staff', 'owner']

function normalizeForHinting(value: string): string {
  return value.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
}

export function suggestStaffRoleIds(roles: readonly Role[]): readonly DiscordSnowflake[] {
  return roles
    .filter((role) => STAFF_NAME_HINTS.some((hint) => normalizeForHinting(role.name).includes(hint)))
    .map((role) => role.id)
}
