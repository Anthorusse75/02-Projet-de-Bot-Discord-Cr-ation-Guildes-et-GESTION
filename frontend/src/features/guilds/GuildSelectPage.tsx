import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { useGuilds } from '../../api/queries'
import type { Guild, Me } from '../../api/types'
import { discordSnowflake } from '../../shared/discord-id'
import { useSessionStore } from '../../shared/state/session'
import { Badge, EmptyState, ErrorState, Skeleton } from '../../shared/components/ui'
import { LanguageSelector } from './LanguageSelector'

type SelectableGuild = Guild & {
  dashboard_access?: boolean
  can_bootstrap?: boolean
  blocked_reason?: string | null
  icon_hash?: string | null
}

export function GuildSelectPage() {
  const { t } = useTranslation()
  const me = useOutletContext<Me>()
  const guilds = useGuilds(me.user.discord_user_id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const setMe = useSessionStore((state) => state.setMe)
  const [opening, setOpening] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function openGuild(guild: SelectableGuild) {
    if (guild.installation_status !== 'ACTIVE' && !guild.can_bootstrap) return
    setOpening(guild.guild_id)
    setActionError(null)
    try {
      const result = await apiRequest<{guild_id:string;csrf_token:string;policy_version:number}>(`/api/v1/guilds/${guild.guild_id}/select`, { method: 'POST' })
      const updated: Me = {
        ...me,
        active_guild_id: discordSnowflake(result.guild_id),
        csrf_token: result.csrf_token,
        policy_version: result.policy_version,
      }
      setMe(updated)
      queryClient.setQueryData(['did', 'identity'], updated)
      navigate(guild.installation_status === 'ACTIVE' ? `/guild/${result.guild_id}/overview` : `/guild/${result.guild_id}/setup`)
    } catch {
      setActionError(t('errors.authorization.denied'))
      setOpening(null)
    }
  }

  async function logout() {
    await apiRequest('/auth/logout', { method: 'POST' })
    setMe(null)
    queryClient.clear()
    navigate('/login')
  }

  return (
    <main id="main" className="guild-hub">
      <header className="guild-hub-topbar">
        <div className="onboarding-brand"><span className="brand-mark">D</span><div><strong>DID</strong><small>{t('app.title')}</small></div></div>
        <div className="guild-hub-account">
          <LanguageSelector />
          <div className="user-pill"><span className="user-avatar">{(me.user.global_name ?? me.user.username).slice(0, 2).toUpperCase()}</span><span>{me.user.global_name ?? me.user.username}</span></div>
          <button type="button" className="button quiet" onClick={() => void logout()}>{t('auth.logout')}</button>
        </div>
      </header>

      <section className="guild-hub-content">
        <div className="guild-hub-intro">
          <p className="eyebrow">Discord Infrastructure Designer</p>
          <h1>{t('guilds.title')}</h1>
          <p>{t('guilds.subtitle')}</p>
        </div>

        {guilds.isLoading && <div className="guild-card-grid"><Skeleton /><Skeleton /></div>}
        {guilds.isError && <ErrorState retry={() => void guilds.refetch()} />}
        {guilds.data?.length === 0 && <EmptyState messageKey="guilds.empty" />}
        {actionError && <div className="onboarding-callout danger" role="alert">{actionError}</div>}

        <div className="guild-card-grid">
          {(guilds.data as SelectableGuild[] | undefined)?.map((guild) => {
            const active = guild.installation_status === 'ACTIVE'
            const blocked = !active && !guild.can_bootstrap
            return (
              <article className={`guild-card ${blocked ? 'blocked' : ''}`} key={guild.guild_id}>
                <div className="guild-card-cover"><span>{guild.name.slice(0, 2).toUpperCase()}</span></div>
                <div className="guild-card-body">
                  <div className="guild-card-title-row">
                    <div><h2>{guild.name}</h2><small>ID {guild.guild_id}</small></div>
                    <Badge tone={active ? 'ok' : blocked ? 'danger' : 'warning'}>{t(active ? 'guilds.active' : blocked ? 'onboarding.blocked' : 'guilds.pending')}</Badge>
                  </div>
                  <p className="guild-card-state">{active ? t('overview.subtitle') : blocked ? t(guild.blocked_reason === 'TENANT_ACCESS_DENIED' ? 'guilds.noAccess' : 'guilds.blocked') : t('onboarding.subtitle')}</p>
                  <button
                    type="button"
                    className="button primary guild-card-action"
                    disabled={blocked || opening !== null}
                    onClick={() => void openGuild(guild)}
                  >
                    {opening === guild.guild_id ? t('common.loading') : t(active ? 'guilds.select' : 'guilds.setup')}
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      </section>
    </main>
  )
}
