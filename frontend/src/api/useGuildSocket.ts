import { useEffect, useState } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { DiscordSnowflake } from '../shared/discord-id'
import { queryKeys } from './queryKeys'

export type GuildConnection = 'live' | 'reconnecting' | 'offline' | 'unauthorized'
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

export function useGuildSocket(queryClient: QueryClient, userId: DiscordSnowflake, guildId: DiscordSnowflake): GuildConnection {
  const [connection, setConnection] = useState<GuildConnection>('reconnecting')

  useEffect(() => {
    let current = true
    let lastSequence = 0
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let attempt = 0
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'

    function clearRetry() {
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer)
        retryTimer = undefined
      }
    }

    function scheduleReconnect() {
      if (!current || retryTimer !== undefined) return
      if (!navigator.onLine) {
        setConnection('offline')
        return
      }
      setConnection('reconnecting')
      retryTimer = window.setTimeout(() => {
        retryTimer = undefined
        connect()
      }, reconnectDelay(attempt))
      attempt += 1
    }

    function connect() {
      if (!current) return
      clearRetry()
      if (!navigator.onLine) {
        setConnection('offline')
        return
      }
      setConnection('reconnecting')
      socket = new WebSocket(`${protocol}//${location.host}/ws/v1/guilds/${guildId}`)
      socket.onopen = () => {
        if (!current) return
        attempt = 0
        setConnection('live')
      }
      socket.onclose = (event) => {
        socket = null
        if (!current || event.code === 1000) return
        // 4401/4403 are deliberate server-side authorization decisions. Retrying
        // those every few hundred milliseconds only floods the console and Redis.
        if (event.code === 4401 || event.code === 4403) {
          clearRetry()
          setConnection('unauthorized')
          return
        }
        scheduleReconnect()
      }
      socket.onerror = () => {
        if (current && navigator.onLine) setConnection('reconnecting')
      }
      socket.onmessage = (message) => {
        if (!current) return
        let event: GuildEvent
        try {
          event = JSON.parse(String(message.data)) as GuildEvent
        } catch {
          void queryClient.invalidateQueries({ queryKey: ['did', userId, guildId] })
          return
        }
        const decision = resolveGuildEvent(event, guildId, lastSequence)
        lastSequence = decision.nextSequence
        if (decision.kind === 'full') void queryClient.invalidateQueries({ queryKey: ['did', userId, guildId] })
        if (decision.kind === 'feature' && decision.feature) void queryClient.invalidateQueries({ queryKey: queryKeys.tenant(userId, guildId, decision.feature) })
      }
    }

    const onOnline = () => {
      if (!current || socket?.readyState === WebSocket.OPEN) return
      attempt = 0
      connect()
    }
    const onOffline = () => {
      clearRetry()
      setConnection('offline')
      socket?.close(1000, 'browser-offline')
      socket = null
    }

    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    connect()
    return () => {
      current = false
      clearRetry()
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
      socket?.close(1000, 'tenant-change')
    }
  }, [guildId, queryClient, userId])

  return connection
}
