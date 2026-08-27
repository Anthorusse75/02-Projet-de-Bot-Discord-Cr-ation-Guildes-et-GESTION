import { useQuery } from '@tanstack/react-query'
import { discordSnowflake, type DiscordSnowflake } from '../shared/discord-id'
import { useSessionStore } from '../shared/state/session'
import { apiRequest } from './client'
import { queryKeys } from './queryKeys'
import type { AuditEvent, Guild, Me, Plan, PortableArtifact, Roles, Structure, Template } from './types'

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
  return { queryKey: queryKeys.tenant(userId, guildId, feature), queryFn: () => apiRequest<T>(path) }
}
export const useStructure = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<Structure>(u,g,'structure',`/api/v1/guilds/${g}/structure`))
export const useRoles = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<Roles>(u,g,'roles',`/api/v1/guilds/${g}/roles`))
export const useCoverage = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<Record<string, unknown>>(u,g,'coverage',`/api/v1/guilds/${g}/coverage`))
export const usePlans = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{plans:Plan[]}>(u,g,'plans',`/api/v1/guilds/${g}/plans`))
export const useAudit = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{events:AuditEvent[]}>(u,g,'audit',`/api/v1/guilds/${g}/audit`))
export const useTemplates = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{templates:Template[]}>(u,g,'templates',`/api/v1/guilds/${g}/templates`))
export const useLibrary = (u: DiscordSnowflake) => useQuery({ queryKey: queryKeys.library(u), queryFn: () => apiRequest<{artifacts:PortableArtifact[]}>('/api/v1/me/portable-artifacts') })

