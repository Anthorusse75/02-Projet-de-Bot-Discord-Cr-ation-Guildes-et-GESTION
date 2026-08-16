import { useEffect, useState } from 'react'

import { t } from '../i18n/stage02'
import { discordSnowflake, type DiscordSnowflake } from '../shared/discord-id'

type MeResponse = {
  authenticated: true
  user: { discord_user_id: DiscordSnowflake; username: string; global_name: string | null }
  active_guild_id: DiscordSnowflake | null
  csrf_token: string
  policy_version: number
}

type Guild = {
  guild_id: DiscordSnowflake
  name: string
  owner: boolean
  permissions: string
  installation_status: string | null
}

type SessionState =
  | { kind: 'loading' }
  | { kind: 'anonymous' }
  | { kind: 'error' }
  | { kind: 'authenticated'; me: MeResponse; guilds: Guild[] }

export function AuthTenantShell() {
  const [state, setState] = useState<SessionState>({ kind: 'loading' })

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const meResponse = await fetch('/api/v1/me', { credentials: 'include' })
        if (meResponse.status === 401) {
          if (active) setState({ kind: 'anonymous' })
          return
        }
        if (!meResponse.ok) throw new Error('session')
        const me = (await meResponse.json()) as MeResponse
        const guildResponse = await fetch('/api/v1/guilds', { credentials: 'include' })
        if (!guildResponse.ok) throw new Error('guilds')
        const payload = (await guildResponse.json()) as { guilds: Guild[] }
        const guilds = payload.guilds.map((guild) => ({
          ...guild,
          guild_id: discordSnowflake(guild.guild_id),
        }))
        if (active) setState({ kind: 'authenticated', me, guilds })
      } catch {
        if (active) setState({ kind: 'error' })
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [])

  async function selectGuild(guildId: DiscordSnowflake) {
    if (state.kind !== 'authenticated') return
    const response = await fetch(`/api/v1/guilds/${guildId}/select`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Token': state.me.csrf_token },
    })
    if (!response.ok) {
      setState({ kind: 'error' })
      return
    }
    const payload = (await response.json()) as {
      guild_id: DiscordSnowflake
      csrf_token: string
      policy_version: number
    }
    setState({
      ...state,
      me: {
        ...state.me,
        active_guild_id: discordSnowflake(payload.guild_id),
        csrf_token: payload.csrf_token,
        policy_version: payload.policy_version,
      },
    })
  }

  async function logout() {
    if (state.kind !== 'authenticated') return
    await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Token': state.me.csrf_token },
    })
    setState({ kind: 'anonymous' })
  }

  return (
    <main className="shell">
      <h1>{t('app.title')}</h1>
      {state.kind === 'loading' && <p role="status">{t('auth.loading')}</p>}
      {state.kind === 'anonymous' && (
        <a className="primary-action" href="/auth/discord/login">
          {t('auth.login')}
        </a>
      )}
      {state.kind === 'error' && <p role="alert">{t('auth.error')}</p>}
      {state.kind === 'authenticated' && (
        <section aria-labelledby="guild-list-title">
          <div className="session-row">
            <span>{state.me.user.global_name ?? state.me.user.username}</span>
            <button type="button" onClick={() => void logout()}>
              {t('auth.logout')}
            </button>
          </div>
          <h2 id="guild-list-title">{t('guilds.title')}</h2>
          {state.guilds.length === 0 ? (
            <p>{t('guilds.empty')}</p>
          ) : (
            <ul className="guild-list">
              {state.guilds.map((guild) => (
                <li key={guild.guild_id}>
                  <span>{guild.name}</span>
                  <small>
                    {guild.installation_status === 'ACTIVE'
                      ? t('guilds.active')
                      : t('guilds.pending')}
                  </small>
                  <button type="button" onClick={() => void selectGuild(guild.guild_id)}>
                    {t('guilds.select')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  )
}
