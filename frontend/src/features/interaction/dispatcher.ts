import { apiRequest } from '../../api/client'
import type { DiscordSnowflake } from '../../shared/discord-id'
import { actions, type AppAction, type ResourceRef } from './actions'

export type ActionIntent = {
  actionId: AppAction['id']
  source: ResourceRef[]
  destination?: ResourceRef
  createdAt: number
}

export type DispatchResult =
  | { kind: 'ROUTE'; path: string }
  | { kind: 'PLAN'; planId: string; path: string }
  | { kind: 'TRANSFER'; transferStatus: string; planId?: string; path: string }

export function createActionIntent(actionId: string, source: ResourceRef[], destination?: ResourceRef): ActionIntent {
  if (!actions.some((action) => action.id === actionId)) throw new Error('ACTION_UNKNOWN')
  if (source.length === 0) throw new Error('ACTION_SOURCE_REQUIRED')
  return { actionId, source: [...source], ...(destination ? { destination } : {}), createdAt: Date.now() }
}

function moveGraph(intent: ActionIntent) {
  const parentId = intent.destination?.type === 'CATEGORY' ? intent.destination.id : null
  return {
    schema_version: 'did-dsg-v1',
    nodes: intent.source.map((source, index) => ({
      logical_key: `dashboard.move.${source.type.toLowerCase()}.${source.id}.${index}`,
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

export function transferBody(intent: ActionIntent) {
  const destination = intent.destination
  if (!destination || intent.source.some((source) => source.guildId === destination.guildId)) throw new Error('CROSS_GUILD_DESTINATION_REQUIRED')
  const categories = intent.source.filter((source) => source.type === 'CATEGORY')
  const channels = intent.source.filter((source) => source.type === 'CHANNEL')
  return {
    source_guild_id: intent.source[0]?.guildId,
    destination_guild_id: destination.guildId,
    selection: {
      artifact_type: categories.length && channels.length ? 'CUSTOM_BUNDLE' : categories.length ? 'CATEGORY' : 'CHANNEL',
      category_ids: categories.map((source) => source.id),
      channel_ids: channels.map((source) => source.id),
      role_ids: [],
    },
    mode: 'COPY_AS_NEW', mappings: [],
  }
}

export async function dispatchAction(intent: ActionIntent, activeGuildId: DiscordSnowflake, phase: 'PREVIEW'|'EXECUTE' = 'EXECUTE'): Promise<DispatchResult> {
  if (intent.actionId === 'explain') return { kind: 'ROUTE', path: `/guild/${activeGuildId}/permissions` }
  if (intent.actionId === 'open') return { kind: 'ROUTE', path: `/guild/${activeGuildId}/structure` }
  if (intent.actionId === 'move') {
    const response = await apiRequest<{plan: {id: string; state_version: number}}>(`/api/v1/guilds/${activeGuildId}/plans`, {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: moveGraph(intent),
    })
    await apiRequest(`/api/v1/guilds/${activeGuildId}/plans/${response.plan.id}/validate`, { method: 'POST', body: { expected_version: response.plan.state_version } })
    return { kind: 'PLAN', planId: response.plan.id, path: `/guild/${activeGuildId}/plans` }
  }
  if (intent.actionId === 'copy' || intent.actionId === 'clone') {
    if (phase === 'PREVIEW' || !intent.destination || intent.destination.guildId === intent.source[0]?.guildId) return { kind: 'ROUTE', path: `/guild/${activeGuildId}/clone` }
    const response = await apiRequest<{transfer: {status: string}; plan?: {id: string}}>('/api/v1/transfers', {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: transferBody(intent),
    })
    return { kind: 'TRANSFER', transferStatus: response.transfer.status, ...(response.plan ? { planId: response.plan.id } : {}), path: `/guild/${intent.destination.guildId}/plans` }
  }
  return { kind: 'ROUTE', path: `/guild/${activeGuildId}/structure` }
}
