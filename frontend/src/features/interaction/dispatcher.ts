import { apiRequest } from '../../api/client'
import type { DiscordSnowflake } from '../../shared/discord-id'
import { actions, type ActionId, type ResourceRef } from './actions'

export type ActionIntent = {
  actionId: ActionId
  source: ResourceRef[]
  destination?: ResourceRef
  translation?: {
    variantType?: 'CATEGORY' | 'CHANNEL'
    desiredName?: string
    channelType?: 0 | 2 | 5 | 13 | 15 | 16
    translationChannelGroupId?: string
    translationCategoryVariantId?: string
    discordResourceId?: string
  }
  createdAt: number
}

export type DispatchResult =
  | { kind: 'ROUTE'; path: string }
  | { kind: 'PLAN'; planId: string; path: string }
  | { kind: 'TRANSFER'; transferStatus: string; planId?: string; path: string }
  | { kind: 'EXPORT'; artifactId: string; path: string }
  | { kind: 'LINK'; variantId: string; path: string }
  | { kind: 'PREVIEW'; group: Record<string, unknown>; path: string }

export const handledActionIds = new Set<ActionId>(['open','move','copy','clone','export','explain','bulk','CREATE_VARIANT','LINK_EXISTING_VARIANT','CLONE_UNLINKED','PREVIEW'])

export function createActionIntent(actionId: string, source: ResourceRef[], destination?: ResourceRef, translation?: ActionIntent['translation']): ActionIntent {
  if (!actions.some((action) => action.id === actionId)) throw new Error('ACTION_UNKNOWN')
  if (source.length === 0) throw new Error('ACTION_SOURCE_REQUIRED')
  return { actionId: actionId as ActionId, source: [...source], ...(destination ? { destination } : {}), ...(translation ? { translation } : {}), createdAt: Date.now() }
}

function moveGraph(intent: ActionIntent) {
  if (!intent.destination) throw new Error('ACTION_DESTINATION_REQUIRED')
  const parentId = intent.destination.type === 'CATEGORY' ? intent.destination.id : null
  return {
    schema_version: 'did-dsg-v1',
    nodes: intent.source.map((source, index) => ({
      logical_key: `dashboard.${intent.actionId}.${source.type.toLowerCase()}.${source.id}.${index}`,
      resource_type: source.type,
      discord_id: source.id,
      presence: 'PRESENT',
      properties: source.type === 'CATEGORY'
        ? { name: source.name, position: source.position ?? 0 }
        : { type: source.channelType ?? 0, name: source.name, position: source.position ?? 0, parent_id: parentId },
      relations: [],
    })),
  }
}

function selection(source: ResourceRef[]) {
  const categories = source.filter((item) => item.type === 'CATEGORY')
  const channels = source.filter((item) => item.type === 'CHANNEL')
  return {
    artifact_type: categories.length && channels.length ? 'CUSTOM_BUNDLE' : categories.length ? 'CATEGORY' : 'CHANNEL',
    category_ids: categories.map((item) => item.id),
    channel_ids: channels.map((item) => item.id),
    role_ids: [],
  }
}

export function transferBody(intent: ActionIntent) {
  const destination = intent.destination
  if (!destination || intent.source.some((source) => source.guildId === destination.guildId)) throw new Error('CROSS_GUILD_DESTINATION_REQUIRED')
  return {
    source_guild_id: intent.source[0]?.guildId,
    destination_guild_id: destination.guildId,
    selection: selection(intent.source),
    mode: 'COPY_AS_NEW', mappings: [],
  }
}

export function exportBody(intent: ActionIntent) {
  return { selection: selection(intent.source), kind: 'LIBRARY' as const }
}

async function createAndValidatePlan(intent: ActionIntent, guildId: DiscordSnowflake): Promise<DispatchResult> {
  const response = await apiRequest<{plan: {id: string; state_version: number}}>(`/api/v1/guilds/${guildId}/plans`, {
    method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: moveGraph(intent),
  })
  await apiRequest(`/api/v1/guilds/${guildId}/plans/${response.plan.id}/validate`, { method: 'POST', body: { expected_version: response.plan.state_version } })
  return { kind: 'PLAN', planId: response.plan.id, path: `/guild/${guildId}/plans` }
}

export async function dispatchAction(intent: ActionIntent, activeGuildId: DiscordSnowflake, phase: 'PREVIEW'|'EXECUTE' = 'EXECUTE'): Promise<DispatchResult> {
  switch (intent.actionId) {
    case 'PREVIEW': {
      const source = intent.source[0]
      if (!source || source.type !== 'TRANSLATION_GROUP') throw new Error('TRANSLATION_GROUP_REQUIRED')
      const group = await apiRequest<Record<string, unknown>>(`/api/v1/guilds/${source.guildId}/translation-groups/${source.id}`)
      return { kind: 'PREVIEW', group, path: `/guild/${source.guildId}/translations` }
    }
    case 'CREATE_VARIANT': {
      const source = intent.source[0]; const destination = intent.destination; const fields = intent.translation
      if (!source || source.type !== 'TRANSLATION_GROUP') throw new Error('TRANSLATION_GROUP_REQUIRED')
      if (!destination || destination.type !== 'LANGUAGE_TARGET' || destination.parentId !== source.id) throw new Error('LANGUAGE_TARGET_REQUIRED')
      if (!fields?.variantType || !fields.desiredName) throw new Error('VARIANT_DETAILS_REQUIRED')
      const response = await apiRequest<{plan_id:string}>(`/api/v1/guilds/${source.guildId}/translation-groups/${source.id}/variants/plan`, {
        method: 'POST',
        body: {
          variant_type: fields.variantType,
          language_profile_id: destination.id,
          desired_name: fields.desiredName,
          channel_type: fields.channelType ?? 0,
          translation_channel_group_id: fields.translationChannelGroupId ?? null,
          idempotency_key: crypto.randomUUID(),
        },
      })
      return { kind: 'PLAN', planId: response.plan_id, path: `/guild/${source.guildId}/plans` }
    }
    case 'LINK_EXISTING_VARIANT': {
      const source = intent.source[0]; const destination = intent.destination; const fields = intent.translation
      if (!source || source.type !== 'TRANSLATION_GROUP') throw new Error('TRANSLATION_GROUP_REQUIRED')
      if (!destination || destination.type !== 'LANGUAGE_TARGET' || destination.parentId !== source.id) throw new Error('LANGUAGE_TARGET_REQUIRED')
      if (!fields?.variantType || !fields.discordResourceId) throw new Error('LINK_DETAILS_REQUIRED')
      const response = await apiRequest<{id:string}>(`/api/v1/guilds/${source.guildId}/translation-groups/${source.id}/link`, {
        method: 'POST',
        body: {
          language_profile_id: destination.id,
          variant_type: fields.variantType,
          discord_resource_id: fields.discordResourceId,
          confirmed_explicit_selection: true,
          translation_channel_group_id: fields.translationChannelGroupId ?? null,
          translation_category_variant_id: fields.translationCategoryVariantId ?? null,
        },
      })
      return { kind: 'LINK', variantId: response.id, path: `/guild/${source.guildId}/translations` }
    }
    case 'CLONE_UNLINKED': {
      const source = intent.source[0]; const destination = intent.destination
      if (!source || source.type !== 'TRANSLATION_GROUP') throw new Error('TRANSLATION_GROUP_REQUIRED')
      if (!destination || destination.type !== 'GUILD' || destination.guildId === source.guildId) throw new Error('CROSS_GUILD_DESTINATION_REQUIRED')
      const response = await apiRequest<{destination_plan_id:string|null;transfer_status:string}>(`/api/v1/guilds/${source.guildId}/multilingual-clone/plan`, {
        method: 'POST',
        body: { destination_guild_id: destination.guildId, translation_group_id: source.id, mode: 'COPY_AS_NEW', idempotency_key: crypto.randomUUID() },
      })
      return { kind: 'TRANSFER', transferStatus: response.transfer_status, ...(response.destination_plan_id ? { planId: response.destination_plan_id } : {}), path: `/guild/${destination.guildId}/plans` }
    }
    case 'explain': return { kind: 'ROUTE', path: `/guild/${activeGuildId}/permissions` }
    case 'open': return { kind: 'ROUTE', path: `/guild/${activeGuildId}/structure` }
    case 'move':
    case 'bulk':
      return createAndValidatePlan(intent, activeGuildId)
    case 'copy':
    case 'clone': {
      if (phase === 'PREVIEW' || !intent.destination || intent.destination.guildId === intent.source[0]?.guildId) return { kind: 'ROUTE', path: `/guild/${activeGuildId}/clone` }
      const response = await apiRequest<{transfer: {status: string}; plan?: {id: string}}>('/api/v1/transfers', {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: transferBody(intent),
      })
      return { kind: 'TRANSFER', transferStatus: response.transfer.status, ...(response.plan ? { planId: response.plan.id } : {}), path: `/guild/${intent.destination.guildId}/plans` }
    }
    case 'export': {
      const sourceGuildId = intent.source[0]?.guildId
      if (!sourceGuildId) throw new Error('ACTION_SOURCE_REQUIRED')
      const response = await apiRequest<{artifact: {id: string}}>(`/api/v1/guilds/${sourceGuildId}/exports/portable`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: exportBody(intent),
      })
      return { kind: 'EXPORT', artifactId: response.artifact.id, path: `/guild/${activeGuildId}/library` }
    }
    default: throw new Error('ACTION_UNHANDLED')
  }
}
