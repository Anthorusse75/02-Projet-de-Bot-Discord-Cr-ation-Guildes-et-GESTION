import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../api/client'
import { useDashboardCapabilities, useGuilds } from '../api/queries'
import type { DashboardCapabilities, Guild, Me } from '../api/types'
import { leaveTenant } from '../api/tenantLifecycle'
import { useGuildSocket, type GuildConnection } from '../api/useGuildSocket'
import { discordSnowflake, type DiscordSnowflake } from '../shared/discord-id'
import { Badge, Status } from '../shared/components/ui'
import { useInteractionStore } from '../shared/state/interaction'
import { useSessionStore } from '../shared/state/session'
import { LanguageSelector } from '../features/guilds/LanguageSelector'
import { CommandPalette } from '../features/search/CommandPalette'

export type DashboardContext = {
  me: Me
  guild: Guild
  guilds: Guild[]
  connection: GuildConnection
  capabilities: DashboardCapabilities | undefined
}

type RuntimeFeatures = { features: { oauth: boolean; live_events: boolean; portability: boolean } }
type ShellGuild = Guild & { can_bootstrap?: boolean; dashboard_access?: boolean }

const navGroups = [
  { label: 'shell.workspace', sections: ['overview', 'structure', 'roles', 'permissions', 'policies'] as const },
  { label: 'nav.plans', sections: ['plans', 'diagnostics', 'audit'] as const },
  { label: 'nav.translations', sections: ['translations', 'campaigns'] as const },
  { label: 'nav.templates', sections: ['templates', 'library', 'clone'] as const },
]
const portabilitySections = new Set(['templates', 'library', 'clone'])

const sectionGlyph: Record<string, string> = {
  overview: '⌂', structure: '⌘', roles: '◇', permissions: '◈', policies: '◆', plans: '▱', diagnostics: '◌', audit: '≡',
  translations: '文', campaigns: '✦', templates: '▣', library: '▤', clone: '⇄',
}

export function AppShell() {
  const { t } = useTranslation()
  const me = useOutletContext<Me>()
  const { guildId } = useParams()
  const guilds = useGuilds(me.user.discord_user_id)
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const setMe = useSessionStore((state) => state.setMe)
  const setCommandOpen = useInteractionStore((state) => state.setCommandOpen)
  const parsedGuild = guildId ? discordSnowflake(guildId) : null
  const connection = useGuildSocket(queryClient, me.user.discord_user_id, parsedGuild ?? me.user.discord_user_id)
  const featureQuery = useQuery({
    queryKey: ['did', 'runtime-features'],
    queryFn: () => apiRequest<RuntimeFeatures>('/health/features', { anonymous: true }),
    staleTime: 30_000,
  })

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }
    }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [setCommandOpen])

  if (!parsedGuild) return <Navigate to="/guilds" replace />
  const currentGuildId = parsedGuild
  const guild = guilds.data?.find((item) => item.guild_id === currentGuildId) as ShellGuild | undefined
  const capabilityQuery = useDashboardCapabilities(me.user.discord_user_id, currentGuildId)

  if (!guilds.data) return <main className="shell"><Status>{t('common.loading')}</Status></main>
  if (!guild) return <Navigate to="/guilds" replace />
  if (guild.installation_status !== 'ACTIVE') return <Navigate to={`/guild/${currentGuildId}/setup`} replace />

  const portabilityAvailable = featureQuery.data?.features.portability !== false
  const activeSection = location.pathname.split('/').at(-1) ?? 'overview'
  const connectionLabel = connection === 'live'
    ? t('connection.live')
    : connection === 'offline'
      ? t('errors.network.offline')
      : connection === 'unauthorized'
        ? t('errors.authorization.denied')
        : t('connection.reconnecting')
  const connectionTone = connection === 'live' ? 'ok' : connection === 'unauthorized' ? 'danger' : 'warning'

  async function switchGuild(next: DiscordSnowflake) {
    if (next === currentGuildId) return
    const target = guilds.data?.find((item) => item.guild_id === next) as ShellGuild | undefined
    if (!target) return
    await leaveTenant(queryClient, me.user.discord_user_id, currentGuildId)
    try {
      const result = await apiRequest<{guild_id:string;csrf_token:string;policy_version:number}>(`/api/v1/guilds/${next}/select`, { method:'POST' })
      const updated: Me = {
        ...me,
        active_guild_id: discordSnowflake(result.guild_id),
        csrf_token: result.csrf_token,
        policy_version: result.policy_version,
      }
      setMe(updated)
      queryClient.setQueryData(['did', 'identity'], updated)
      if (target.installation_status !== 'ACTIVE') {
        navigate(`/guild/${next}/setup`)
        return
      }
      const section = portabilitySections.has(activeSection) && !portabilityAvailable ? 'overview' : activeSection
      navigate(`/guild/${next}/${section}`)
    } catch {
      navigate('/guilds')
    }
  }

  return (
    <div className="premium-app-layout">
      <a href="#main" className="skip-link">{t('app.skip')}</a>
      <aside className="premium-sidebar">
        <div className="premium-brand">
          <span className="brand-mark">D</span>
          <div><strong>DID</strong><small>{t('app.title')}</small></div>
        </div>

        <button type="button" className="active-server-card" onClick={() => navigate('/guilds')}>
          <span className="server-emblem small">{guild.name.slice(0, 2).toUpperCase()}</span>
          <span className="active-server-copy"><small>{t('guilds.switch')}</small><strong>{guild.name}</strong></span>
          <span aria-hidden="true">⌄</span>
        </button>

        <div className="sidebar-scroll">
          {navGroups.map((group) => (
            <section className="nav-group" key={group.label}>
              <p>{t(group.label)}</p>
              <nav>
                {group.sections.map((section) => {
                  const disabled = portabilitySections.has(section) && !portabilityAvailable
                  if (disabled) {
                    return <span className="nav-link nav-disabled" key={section} title={t('common.readOnly')}><span>{sectionGlyph[section]}</span>{t(`nav.${section}`)}</span>
                  }
                  return (
                    <NavLink key={section} className="nav-link" to={`/guild/${currentGuildId}/${section}`}>
                      <span>{sectionGlyph[section]}</span>{t(`nav.${section}`)}
                    </NavLink>
                  )
                })}
              </nav>
            </section>
          ))}

          <section className="recent-servers">
            <p>{t('shell.recentServers')}</p>
            {(guilds.data as ShellGuild[]).filter((item) => item.installation_status === 'ACTIVE').slice(0, 4).map((item) => (
              <button type="button" key={item.guild_id} className={item.guild_id === currentGuildId ? 'active' : ''} onClick={() => void switchGuild(item.guild_id)}>
                <span className="recent-server-dot">{item.name.slice(0, 1).toUpperCase()}</span><span>{item.name}</span>
              </button>
            ))}
          </section>
        </div>

        {!portabilityAvailable && (
          <div className="sidebar-preflight-warning"><span>!</span><div><strong>{t('nav.library')}</strong><small>{t('common.readOnly')}</small></div></div>
        )}

        <button type="button" className="sidebar-user" onClick={() => setCommandOpen(true)}>
          <span className="user-avatar">{(me.user.global_name ?? me.user.username).slice(0, 2).toUpperCase()}</span>
          <span><strong>{me.user.global_name ?? me.user.username}</strong><small>@{me.user.username}</small></span>
          <kbd>⌘K</kbd>
        </button>
      </aside>

      <div className="premium-workspace">
        <header className="premium-topbar">
          <button type="button" className="global-search" onClick={() => setCommandOpen(true)}>
            <span aria-hidden="true">⌕</span><span>{t('shell.searchHint')}</span><kbd>Ctrl K</kbd>
          </button>
          <div className="topbar-actions">
            <Badge tone={connectionTone}><span className={`connection-led ${connection}`} />{connectionLabel}</Badge>
            <LanguageSelector />
            <span className="topbar-avatar">{(me.user.global_name ?? me.user.username).slice(0, 2).toUpperCase()}</span>
          </div>
        </header>
        <main id="main" className="premium-content">
          <Outlet context={{ me, guild, guilds: guilds.data, connection, capabilities: capabilityQuery.data } satisfies DashboardContext} />
        </main>
      </div>
      <CommandPalette guild={guild} capabilities={capabilityQuery.data} />
    </div>
  )
}
