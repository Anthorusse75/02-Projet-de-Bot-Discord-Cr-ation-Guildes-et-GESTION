import { useEffect, useState } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { DiscordSnowflake } from '../shared/discord-id'
import { queryKeys } from './queryKeys'

type Connection = 'live' | 'reconnecting'
export type GuildEvent = { guild_id?: string; sequence?: number; version?: number; type?: string }
export type GuildEventDecision = { kind: 'ignore' | 'full' | 'feature'; feature?: 'plans' | 'audit' | 'structure'; nextSequence: number }

export function resolveGuildEvent(event: GuildEvent, guildId: string, lastSequence: number): GuildEventDecision {
  if (event.guild_id !== guildId || (event.version !== undefined && event.version !== 1)) return { kind: 'ignore', nextSequence: lastSequence }
  const nextSequence = event.sequence ?? lastSequence
  if (event.sequence !== undefined && lastSequence > 0 && event.sequence !== lastSequence + 1) return { kind: 'full', nextSequence }
  const feature = event.type?.startsWith('plan.') ? 'plans' : event.type?.startsWith('audit.') ? 'audit' : 'structure'
  return { kind: 'feature', feature, nextSequence }
}

export function useGuildSocket(queryClient: QueryClient, userId: DiscordSnowflake, guildId: DiscordSnowflake): Connection {
  const [connection, setConnection] = useState<Connection>('reconnecting')
  useEffect(() => {
    let current = true; let lastSequence = 0
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${location.host}/ws/v1/guilds/${guildId}`)
    socket.onopen = () => current && setConnection('live')
    socket.onclose = () => current && setConnection('reconnecting')
    socket.onmessage = (message) => {
      if (!current) return
      const decision = resolveGuildEvent(JSON.parse(String(message.data)) as GuildEvent, guildId, lastSequence)
      lastSequence = decision.nextSequence
      if (decision.kind === 'full') void queryClient.invalidateQueries({ queryKey: ['did', userId, guildId] })
      if (decision.kind === 'feature' && decision.feature) void queryClient.invalidateQueries({ queryKey: queryKeys.tenant(userId, guildId, decision.feature) })
    }
    return () => { current = false; socket.close(1000, 'tenant-change') }
  }, [guildId, queryClient, userId])
  return connection
}
