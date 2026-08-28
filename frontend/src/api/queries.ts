import { useQueries, useQuery } from '@tanstack/react-query'
import { discordSnowflake, type DiscordSnowflake } from '../shared/discord-id'
import { useSessionStore } from '../shared/state/session'
import { apiRequest } from './client'
import { queryKeys } from './queryKeys'
import type { AuditEvent, DashboardCapabilities, Guild, Me, Plan, PlanProgressEvent, PortableArtifact, Roles, Structure, Template } from './types'
import { tenantSignal } from './tenantLifecycle'

export function useMe() {
  const setMe = useSessionStore((state) => state.setMe)
  return useQuery({ queryKey: queryKeys.me, retry: false, queryFn: async () => {
    try {
      const me = await apiRequest<Me>('/api/v1/me')
      const normalized = { ...me, user: { ...me.user, discord_user_id: discordSnowflake(me.user.discord_user_id) }, active_guild_id: me.active_guild_id ? discordSnowflake(me.active_guild_id) : null }
      setMe(normalized); return normalized
    } catch (error) { setMe(null); throw error }
  } })
}

export function useGuilds(userId: DiscordSnowflake | undefined) {
  return useQuery({ enabled: Boolean(userId), queryKey: userId ? queryKeys.guilds(userId) : ['did','anonymous','guilds'], queryFn: async () => {
    const payload = await apiRequest<{ guilds: Guild[] }>('/api/v1/guilds')
    return payload.guilds.map((guild) => ({ ...guild, guild_id: discordSnowflake(guild.guild_id) }))
  } })
}

function tenantQuery<T>(userId: DiscordSnowflake, guildId: DiscordSnowflake, feature: string, path: string) {
  return { queryKey: queryKeys.tenant(userId, guildId, feature), queryFn: () => apiRequest<T>(path, { signal: tenantSignal(guildId) }) }
}
export const useStructure = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<Structure>(u,g,'structure',`/api/v1/guilds/${g}/structure`))
export const useRoles = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<Roles>(u,g,'roles',`/api/v1/guilds/${g}/roles`))
export const useCoverage = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<Record<string, unknown>>(u,g,'coverage',`/api/v1/guilds/${g}/coverage`))
export const usePlans = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{plans:Plan[]}>(u,g,'plans',`/api/v1/guilds/${g}/plans`))
export const useAudit = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{events:AuditEvent[]}>(u,g,'audit',`/api/v1/guilds/${g}/audit`))
export const useTemplates = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{templates:Template[]}>(u,g,'templates',`/api/v1/guilds/${g}/templates`))
export const useLibrary = (u: DiscordSnowflake) => useQuery({ queryKey: queryKeys.library(u), queryFn: () => apiRequest<{artifacts:PortableArtifact[]}>('/api/v1/me/portable-artifacts') })
export const dashboardCapabilitiesOptions = (u: DiscordSnowflake, g: DiscordSnowflake, resourceId?: string) => ({
  queryKey: queryKeys.tenant(u, g, 'dashboard-capabilities', ...(resourceId ? [resourceId] : [])),
  queryFn: () => apiRequest<DashboardCapabilities>(`/api/v1/guilds/${g}/dashboard-capabilities${resourceId ? `?resource_id=${encodeURIComponent(resourceId)}` : ''}`, { signal: tenantSignal(g) }),
})
export const useDashboardCapabilities = (u: DiscordSnowflake, g: DiscordSnowflake, resourceId?: string) => useQuery(dashboardCapabilitiesOptions(u, g, resourceId))
export const useGuildDashboardCapabilities = (u: DiscordSnowflake, guildIds: readonly DiscordSnowflake[]) => useQueries({
  queries: guildIds.map((guildId) => dashboardCapabilitiesOptions(u, guildId)),
})
const terminalPlanStates = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'PARTIALLY_APPLIED', 'VERIFICATION_FAILED', 'STALE', 'INTERVENTION_REQUIRED'])
export const usePlanProgress = (u: DiscordSnowflake, g: DiscordSnowflake, planId: string | undefined) => useQuery({
  enabled: Boolean(planId), queryKey: queryKeys.tenant(u, g, 'plans', planId ?? 'none', 'progress'),
  queryFn: () => apiRequest<{events: PlanProgressEvent[]}>(`/api/v1/guilds/${g}/plans/${planId}/progress`, { signal: tenantSignal(g) }),
  refetchInterval: (query) => {
    const events = query.state.data?.events ?? []
    const status = events.at(-1)?.plan_status
    return status && terminalPlanStates.has(status) ? false : 1_000
  },
})
