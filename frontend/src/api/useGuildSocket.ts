import { useEffect, useState } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { DiscordSnowflake } from '../shared/discord-id'
import { queryKeys } from './queryKeys'

type Connection = 'live' | 'reconnecting'
export type GuildEvent = { guild_id?: string; sequence?: number; version?: number; type?: string }
export type GuildEventDecision = { kind: 'ignore' | 'full' | 'feature'; feature?: 'plans' | 'audit' | 'structure'; nextSequence: number }

export function reconnectDelay(attempt: number): number {
  return Math.min(30_000, 500 * 2 ** Math.min(Math.max(attempt, 0), 6))
}

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
    let socket: WebSocket | null = null; let retryTimer: number | undefined; let attempt = 0
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    function connect() {
      if (!current) return
      socket = new WebSocket(`${protocol}//${location.host}/ws/v1/guilds/${guildId}`)
      socket.onopen = () => { if (current) { attempt = 0; setConnection('live') } }
      socket.onclose = () => {
        if (!current) return
        setConnection('reconnecting')
        retryTimer = window.setTimeout(connect, reconnectDelay(attempt)); attempt += 1
      }
      socket.onmessage = (message) => {
        if (!current) return
        const decision = resolveGuildEvent(JSON.parse(String(message.data)) as GuildEvent, guildId, lastSequence)
        lastSequence = decision.nextSequence
        if (decision.kind === 'full') void queryClient.invalidateQueries({ queryKey: ['did', userId, guildId] })
        if (decision.kind === 'feature' && decision.feature) void queryClient.invalidateQueries({ queryKey: queryKeys.tenant(userId, guildId, decision.feature) })
      }
    }
    connect()
    return () => { current = false; if (retryTimer !== undefined) window.clearTimeout(retryTimer); socket?.close(1000, 'tenant-change') }
  }, [guildId, queryClient, userId])
  return connection
}
