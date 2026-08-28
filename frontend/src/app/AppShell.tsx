import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../api/client'
import { useDashboardCapabilities, useGuilds } from '../api/queries'
import type { DashboardCapabilities, Guild, Me } from '../api/types'
import { leaveTenant } from '../api/tenantLifecycle'
import { useGuildSocket } from '../api/useGuildSocket'
import { discordSnowflake, type DiscordSnowflake } from '../shared/discord-id'
import { Badge, Select, Status } from '../shared/components/ui'
import { useInteractionStore } from '../shared/state/interaction'
import { useSessionStore } from '../shared/state/session'
import { LanguageSelector } from '../features/guilds/LanguageSelector'
import { CommandPalette } from '../features/search/CommandPalette'

export type DashboardContext = { me: Me; guild: Guild; guilds: Guild[]; connection: 'live'|'reconnecting'; capabilities: DashboardCapabilities | undefined }
const sections = ['structure','roles','permissions','plans','diagnostics','audit','templates','library','clone'] as const

export function AppShell() {
  const { t } = useTranslation(); const me = useOutletContext<Me>(); const { guildId } = useParams(); const guilds = useGuilds(me.user.discord_user_id)
  const navigate = useNavigate(); const location = useLocation(); const queryClient = useQueryClient(); const setMe = useSessionStore((state) => state.setMe)
  const setCommandOpen = useInteractionStore((state) => state.setCommandOpen)
  const parsedGuild = guildId ? discordSnowflake(guildId) : null
  const connection = useGuildSocket(queryClient, me.user.discord_user_id, parsedGuild ?? me.user.discord_user_id)
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setCommandOpen(true) } }
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key)
  }, [setCommandOpen])
  if (!parsedGuild) return <Navigate to="/guilds" replace />
  const currentGuildId = parsedGuild
  const guild = guilds.data?.find((item) => item.guild_id === currentGuildId)
  const capabilityQuery = useDashboardCapabilities(me.user.discord_user_id, currentGuildId)
  if (!guilds.data) return <main className="shell"><Status>{t('common.loading')}</Status></main>
  if (!guild) return <Navigate to="/guilds" replace />
  async function switchGuild(next: DiscordSnowflake) {
    if (next === currentGuildId) return
    await leaveTenant(queryClient, me.user.discord_user_id, currentGuildId)
    const result = await apiRequest<{guild_id:string;csrf_token:string;policy_version:number}>(`/api/v1/guilds/${next}/select`, { method:'POST' })
    const updated = { ...me, active_guild_id: discordSnowflake(result.guild_id), csrf_token: result.csrf_token, policy_version: result.policy_version }
    setMe(updated); queryClient.setQueryData(['did','identity'], updated)
    const section = location.pathname.split('/').at(-1) ?? 'structure'; navigate(`/guild/${next}/${section}`)
  }
  return <div className="app-layout"><a href="#main" className="skip-link">{t('app.skip')}</a><aside className="sidebar"><div className="brand"><span className="brand-mark">DID</span><strong>{t('app.title')}</strong></div><Select labelKey="guilds.switch" value={currentGuildId} onChange={(event) => void switchGuild(discordSnowflake(event.target.value))}>{guilds.data.map((item) => <option key={item.guild_id} value={item.guild_id}>{item.name}</option>)}</Select><nav>{sections.map((section) => <NavLink key={section} to={`/guild/${currentGuildId}/${section}`}>{t(`nav.${section}`)}</NavLink>)}</nav><button type="button" className="command-trigger" onClick={() => setCommandOpen(true)}>{t('nav.commands')} <kbd>Ctrl K</kbd></button></aside><div className="workspace"><header className="topbar"><div><strong>{guild.name}</strong><Badge tone={connection === 'live' ? 'ok' : 'warning'}>{t(connection === 'live' ? 'connection.live' : 'connection.reconnecting')}</Badge></div><LanguageSelector /></header><main id="main" className="content"><Outlet context={{ me, guild, guilds: guilds.data, connection, capabilities: capabilityQuery.data } satisfies DashboardContext} /></main></div><CommandPalette guild={guild} capabilities={capabilityQuery.data} /></div>
}
