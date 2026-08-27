import type { QueryClient } from '@tanstack/react-query'
import type { DiscordSnowflake } from '../shared/discord-id'
import { useInteractionStore } from '../shared/state/interaction'

const controllers = new Map<DiscordSnowflake, Set<AbortController>>()

export function tenantSignal(guildId: DiscordSnowflake): AbortSignal {
  const controller = new AbortController()
  const values = controllers.get(guildId) ?? new Set<AbortController>()
  values.add(controller)
  controllers.set(guildId, values)
  return controller.signal
}

export async function leaveTenant(queryClient: QueryClient, userId: DiscordSnowflake, guildId: DiscordSnowflake) {
  controllers.get(guildId)?.forEach((controller) => controller.abort())
  controllers.delete(guildId)
  await queryClient.cancelQueries({ queryKey: ['did', userId, guildId] })
  queryClient.removeQueries({ queryKey: ['did', userId, guildId] })
  useInteractionStore.getState().clearTenantState()
}
