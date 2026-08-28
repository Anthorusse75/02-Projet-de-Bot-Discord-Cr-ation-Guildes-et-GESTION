import { apiRequest } from '../../api/client'
import type { DiscordSnowflake } from '../../shared/discord-id'
import { actions, type ActionId, type ResourceRef } from './actions'

export type ActionIntent = {
  actionId: ActionId
  source: ResourceRef[]
  destination?: ResourceRef
  createdAt: number
}

export type DispatchResult =
  | { kind: 'ROUTE'; path: string }
  | { kind: 'PLAN'; planId: string; path: string }
  | { kind: 'TRANSFER'; transferStatus: string; planId?: string; path: string }
  | { kind: 'EXPORT'; artifactId: string; path: string }

export const handledActionIds = new Set<ActionId>(['open','move','copy','clone','export','explain','bulk'])

export function createActionIntent(actionId: string, source: ResourceRef[], destination?: ResourceRef): ActionIntent {
  if (!actions.some((action) => action.id === actionId)) throw new Error('ACTION_UNKNOWN')
  if (source.length === 0) throw new Error('ACTION_SOURCE_REQUIRED')
  return { actionId: actionId as ActionId, source: [...source], ...(destination ? { destination } : {}), createdAt: Date.now() }
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
