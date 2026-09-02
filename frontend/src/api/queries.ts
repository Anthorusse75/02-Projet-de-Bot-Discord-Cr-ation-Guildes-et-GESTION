import { useQueries, useQuery } from '@tanstack/react-query'
import { discordSnowflake, type DiscordSnowflake } from '../shared/discord-id'
import { useSessionStore } from '../shared/state/session'
import { apiRequest } from './client'
import { queryKeys } from './queryKeys'
import type { AuditEvent, Campaign, CampaignDelivery, CampaignTarget, CampaignTrigger, DashboardCapabilities, GlossaryEntry, Guild, LanguageProfile, Me, Plan, PlanProgressEvent, PortableArtifact, Roles, Structure, Template, TemplateVariable, TranslationWorkspace, TriggerSourceBinding } from './types'
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
export const useTranslationWorkspace = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<TranslationWorkspace>(u,g,'translations',`/api/v1/guilds/${g}/translation-workspace`))
export const useLanguageProfiles = (u: DiscordSnowflake, g: DiscordSnowflake) => useQuery(tenantQuery<{guild_id:DiscordSnowflake;languages:LanguageProfile[]}>(u,g,'languages',`/api/v1/guilds/${g}/languages`))
export const dashboardCapabilitiesOptions = (u: DiscordSnowflake, g: DiscordSnowflake, resourceId?: string) => ({
  queryKey: queryKeys.tenant(u, g, 'dashboard-capabilities', ...(resourceId ? [resourceId] : [])),
  queryFn: () => apiRequest<DashboardCapabilities>(`/api/v1/guilds/${g}/dashboard-capabilities${resourceId ? `?resource_id=${encodeURIComponent(resourceId)}` : ''}`, { signal: tenantSignal(g) }),
})
export const useDashboardCapabilities = (u: DiscordSnowflake, g: DiscordSnowflake, resourceId?: string) => useQuery(dashboardCapabilitiesOptions(u, g, resourceId))
export const useGuildDashboardCapabilities = (u: DiscordSnowflake, guildIds: readonly DiscordSnowflake[]) => useQueries({
  queries: guildIds.map((guildId) => dashboardCapabilitiesOptions(u, guildId)),
})
// STAGE 09 -- campaigns are owned by the caller (not Guild-scoped in the
// URL: a single campaign can target many Guilds), so unlike tenantQuery
// above these keys carry no Guild id at all.
export const useCampaigns = (u: DiscordSnowflake) => useQuery({ queryKey: queryKeys.campaigns(u), queryFn: () => apiRequest<{campaigns:Campaign[]}>('/api/v1/campaigns') })
export const useCampaignTargets = (u: DiscordSnowflake, campaignId: string | undefined) => useQuery({
  enabled: Boolean(campaignId), queryKey: queryKeys.campaignDetail(u, campaignId ?? 'none', 'targets'),
  queryFn: () => apiRequest<{targets:CampaignTarget[]}>(`/api/v1/campaigns/${campaignId}/targets`),
})
export const useCampaignDeliveries = (u: DiscordSnowflake, campaignId: string | undefined) => useQuery({
  enabled: Boolean(campaignId), queryKey: queryKeys.campaignDetail(u, campaignId ?? 'none', 'deliveries'),
  queryFn: () => apiRequest<{deliveries:CampaignDelivery[]}>(`/api/v1/campaigns/${campaignId}/deliveries`),
})
export const useCampaignTemplateVariables = (u: DiscordSnowflake, campaignId: string | undefined) => useQuery({
  enabled: Boolean(campaignId), queryKey: queryKeys.campaignDetail(u, campaignId ?? 'none', 'template-variables'),
  queryFn: () => apiRequest<{template_variables:TemplateVariable[]}>(`/api/v1/campaigns/${campaignId}/template-variables`),
})
// REQ-MSG-014 mission section 11: the three glossary scopes are fetched
// independently -- CAMPAIGN and GLOBAL_USER need only the caller's own id
// and are always safe to fetch, GUILD needs an explicit destination Guild
// id (there is no single "current Guild" for a campaign, which may target
// many) so that query stays disabled until one is entered.
export const useCampaignGlossary = (u: DiscordSnowflake, campaignId: string | undefined) => useQuery({
  enabled: Boolean(campaignId), queryKey: queryKeys.campaignDetail(u, campaignId ?? 'none', 'glossary'),
  queryFn: () => apiRequest<{glossary_entries:GlossaryEntry[]}>(`/api/v1/campaigns/${campaignId}/glossary`),
})
export const useGlobalUserGlossary = (u: DiscordSnowflake) => useQuery({
  queryKey: queryKeys.globalGlossary(u),
  queryFn: () => apiRequest<{glossary_entries:GlossaryEntry[]}>('/api/v1/glossary'),
})
export const useGuildGlossary = (u: DiscordSnowflake, guildId: string) => useQuery({
  enabled: Boolean(guildId), queryKey: queryKeys.guildGlossary(u, guildId),
  queryFn: () => apiRequest<{glossary_entries:GlossaryEntry[]}>(`/api/v1/guilds/${guildId}/glossary`),
})
// REQ-MSG-027/030 mission section 12: triggers are owned by the caller
// (like the campaign itself); their source bindings are Guild-scoped (RLS)
// so, mirroring the Guild glossary/target patterns above, a source list
// stays disabled until an explicit destination Guild id is entered.
export const useCampaignTriggers = (u: DiscordSnowflake, campaignId: string | undefined) => useQuery({
  enabled: Boolean(campaignId), queryKey: queryKeys.campaignDetail(u, campaignId ?? 'none', 'triggers'),
  queryFn: () => apiRequest<{triggers:CampaignTrigger[]}>(`/api/v1/campaigns/${campaignId}/triggers`),
})
export const useTriggerSources = (u: DiscordSnowflake, campaignId: string | undefined, triggerId: string | undefined, guildId: string) => useQuery({
  enabled: Boolean(campaignId && triggerId && guildId),
  queryKey: ['did', u, 'campaigns', campaignId ?? 'none', 'triggers', triggerId ?? 'none', 'sources', guildId || 'none'] as const,
  queryFn: () => apiRequest<{trigger_sources:TriggerSourceBinding[]}>(`/api/v1/campaigns/${campaignId}/triggers/${triggerId}/sources?guild_id=${encodeURIComponent(guildId)}`),
})
const terminalPlanStates = new Set(['SUCCEEDED', 'APPLIED_WITH_PENDING_PROVIDER', 'FAILED', 'CANCELLED', 'PARTIALLY_APPLIED', 'VERIFICATION_FAILED', 'STALE', 'INTERVENTION_REQUIRED'])
export const usePlanProgress = (u: DiscordSnowflake, g: DiscordSnowflake, planId: string | undefined) => useQuery({
  enabled: Boolean(planId), queryKey: queryKeys.tenant(u, g, 'plans', planId ?? 'none', 'progress'),
  queryFn: () => apiRequest<{events: PlanProgressEvent[]}>(`/api/v1/guilds/${g}/plans/${planId}/progress`, { signal: tenantSignal(g) }),
  refetchInterval: (query) => {
    const events = query.state.data?.events ?? []
    const status = events.at(-1)?.plan_status
    return status && terminalPlanStates.has(status) ? false : 1_000
  },
})
