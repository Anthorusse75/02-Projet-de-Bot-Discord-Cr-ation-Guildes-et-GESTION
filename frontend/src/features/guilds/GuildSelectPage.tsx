import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { useGuilds } from '../../api/queries'
import type { Me } from '../../api/types'
import { discordSnowflake } from '../../shared/discord-id'
import { useSessionStore } from '../../shared/state/session'
import { Badge, Button, EmptyState, ErrorState, Skeleton } from '../../shared/components/ui'
import { LanguageSelector } from './LanguageSelector'

export function GuildSelectPage() {
  const { t } = useTranslation(); const me = useOutletContext<Me>(); const guilds = useGuilds(me.user.discord_user_id)
  const navigate = useNavigate(); const queryClient = useQueryClient(); const setMe = useSessionStore((state) => state.setMe)
  async function select(guildId: string) {
    const result = await apiRequest<{guild_id:string;csrf_token:string;policy_version:number}>(`/api/v1/guilds/${guildId}/select`, { method: 'POST' })
    const updated: Me = { ...me, active_guild_id: discordSnowflake(result.guild_id), csrf_token: result.csrf_token, policy_version: result.policy_version }
    setMe(updated); queryClient.setQueryData(['did','identity'], updated); navigate(`/guild/${result.guild_id}/structure`)
  }
  async function logout() { await apiRequest('/auth/logout', { method:'POST' }); setMe(null); queryClient.clear(); navigate('/login') }
  return <main id="main" className="guild-select shell"><div className="session-row"><span>{me.user.global_name ?? me.user.username}</span><LanguageSelector /><Button labelKey="auth.logout" onClick={() => void logout()} /></div><section><h1>{t('guilds.title')}</h1>{guilds.isLoading && <Skeleton />}{guilds.isError && <ErrorState retry={() => void guilds.refetch()} />}{guilds.data?.length === 0 && <EmptyState messageKey="guilds.empty" />}<ul className="guild-list">{guilds.data?.map((guild) => <li key={guild.guild_id}><div><strong>{guild.name}</strong><Badge tone={guild.installation_status === 'ACTIVE' ? 'ok' : 'warning'}>{t(guild.installation_status === 'ACTIVE' ? 'guilds.active' : 'guilds.pending')}</Badge></div><Button labelKey="guilds.select" variant="primary" onClick={() => void select(guild.guild_id)} /></li>)}</ul></section></main>
}
