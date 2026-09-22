import { useEffect, useState } from 'react'
import { ActionIcon, AppShell as MantineAppShell, Badge as MantineBadge, Drawer, Menu, NavLink as MantineNavLink, Tooltip } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Bell,
  ChevronDown,
  CircleHelp,
  Home,
  Menu as MenuIcon,
  Rabbit,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Navigate, Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../api/client'
import { useDashboardCapabilities, useGuilds } from '../api/queries'
import type { DashboardCapabilities, Guild, Me } from '../api/types'
import { useGuildSocket, type GuildConnection } from '../api/useGuildSocket'
import { discordSnowflake } from '../shared/discord-id'
import { Status } from '../shared/components/ui'
import { useInteractionStore } from '../shared/state/interaction'
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
type NavigationItem = { labelKey: string; section: string; sections: string[]; icon: LucideIcon; accent: string }

const primaryNavigation: NavigationItem[] = [
  { labelKey: 'shell.home', section: 'overview', sections: ['overview'], icon: Home, accent: 'violet' },
  { labelKey: 'shell.build', section: 'structure', sections: ['structure', 'roles'], icon: Wrench, accent: 'blue' },
  { labelKey: 'shell.access', section: 'policies', sections: ['policies', 'permissions', 'matrix', 'access-space'], icon: ShieldCheck, accent: 'mint' },
  { labelKey: 'shell.automate', section: 'wizards', sections: ['wizards', 'translations', 'campaigns'], icon: Sparkles, accent: 'rose' },
  { labelKey: 'shell.activity', section: 'plans', sections: ['plans', 'diagnostics', 'audit'], icon: Activity, accent: 'amber' },
]

const expertNavigation: ReadonlyArray<{ labelKey: string; section: string; portability?: boolean }> = [
  { labelKey: 'nav.roles', section: 'roles' },
  { labelKey: 'nav.permissions', section: 'permissions' },
  { labelKey: 'nav.matrix', section: 'matrix' },
  { labelKey: 'nav.diagnostics', section: 'diagnostics' },
  { labelKey: 'nav.audit', section: 'audit' },
  { labelKey: 'nav.translations', section: 'translations' },
  { labelKey: 'nav.campaigns', section: 'campaigns' },
  { labelKey: 'nav.templates', section: 'templates', portability: true },
  { labelKey: 'nav.library', section: 'library', portability: true },
  { labelKey: 'nav.clone', section: 'clone', portability: true },
]

export function AppShell() {
  const { t } = useTranslation()
  const me = useOutletContext<Me>()
  const { guildId } = useParams()
  const guilds = useGuilds(me.user.discord_user_id)
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const setCommandOpen = useInteractionStore((state) => state.setCommandOpen)
  const [navOpen, setNavOpen] = useState(false)
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
      if (event.key === 'Escape') setNavOpen(false)
    }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [setCommandOpen])

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

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
  const connectionColor = connection === 'live' ? 'mint' : connection === 'unauthorized' ? 'coral' : 'amber'
  const userName = me.user.global_name ?? me.user.username

  const navigation = (mobile = false) => (
    <div className="bunny-sidebar-content">
      <div className="bunny-brand">
        <span className="bunny-brand-mark"><Rabbit size={25} strokeWidth={2.4} /></span>
        <span className="bunny-brand-copy"><strong>{t('shell.brand')}</strong><small>{t('shell.tagline')}</small></span>
      </div>

      <button type="button" className="bunny-server-switch" onClick={() => navigate('/guilds')}>
        <span className="bunny-server-emblem">{guild.name.slice(0, 2).toUpperCase()}</span>
        <span><small>{t('guilds.switch')}</small><strong>{guild.name}</strong></span>
        <ChevronDown size={17} aria-hidden="true" />
      </button>

      <nav className="bunny-primary-nav" aria-label={t('shell.workspace')}>
        {primaryNavigation.map((item) => {
          const Icon = item.icon
          return (
            <MantineNavLink
              component={NavLink}
              to={`/guild/${currentGuildId}/${item.section}`}
              key={item.section}
              active={item.sections.includes(activeSection)}
              className={`bunny-nav-link bunny-nav-${item.accent}`}
              label={t(item.labelKey)}
              leftSection={<Icon size={20} strokeWidth={2} />}
              onClick={() => mobile && setNavOpen(false)}
            />
          )
        })}
      </nav>

      <Menu position="top-start" width={230} shadow="md" withinPortal>
        <Menu.Target>
          <button type="button" className="bunny-expert-trigger">
            <SlidersHorizontal size={18} aria-hidden="true" />
            <span>{t('shell.expert')}</span>
            <ChevronDown size={16} aria-hidden="true" />
          </button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Label>{t('shell.expert')}</Menu.Label>
          {expertNavigation.filter((item) => !item.portability || portabilityAvailable).map((item) => (
            <Menu.Item key={item.section} onClick={() => navigate(`/guild/${currentGuildId}/${item.section}`)}>{t(item.labelKey)}</Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>

      <div className="bunny-sidebar-spacer" />
      <button type="button" className="bunny-help-card" onClick={() => navigate(`/guild/${currentGuildId}/wizards`)}>
        <span><CircleHelp size={20} /></span>
        <span><strong>{t('shell.helpTitle')}</strong><small>{t('shell.helpCopy')}</small></span>
      </button>
      <button type="button" className="bunny-user-card" onClick={() => setCommandOpen(true)}>
        <span className="bunny-user-avatar">{userName.slice(0, 2).toUpperCase()}</span>
        <span><strong>{userName}</strong><small>@{me.user.username}</small></span>
        <SlidersHorizontal size={16} aria-hidden="true" />
      </button>
    </div>
  )

  return (
    <MantineAppShell
      className="bunny-app-shell"
      layout="alt"
      header={{ height: { base: 64, md: 72 } }}
      navbar={{ width: 252, breakpoint: 'md', collapsed: { mobile: true } }}
      padding={0}
    >
      <a href="#main" className="skip-link">{t('app.skip')}</a>
      <MantineAppShell.Navbar className="bunny-sidebar" visibleFrom="md">
        {navigation()}
      </MantineAppShell.Navbar>

      <MantineAppShell.Header className="bunny-topbar">
        <div className="bunny-mobile-brand">
          <ActionIcon variant="subtle" color="bunny" size="lg" aria-label={t('shell.openNavigation')} onClick={() => setNavOpen(true)}>
            <MenuIcon size={23} />
          </ActionIcon>
          <span className="bunny-brand-mark small"><Rabbit size={20} /></span>
          <strong>{t('shell.brand')}</strong>
        </div>
        <button type="button" className="bunny-search" onClick={() => setCommandOpen(true)}>
          <Search size={18} aria-hidden="true" />
          <span>{t('shell.searchHint')}</span>
          <kbd>Ctrl K</kbd>
        </button>
        <div className="bunny-topbar-actions">
          <MantineBadge className="bunny-connection" color={connectionColor} variant="light" leftSection={<span className={`bunny-connection-dot ${connection}`} />}>
            {connectionLabel}
          </MantineBadge>
          <Tooltip label={t('shell.notifications')}>
            <ActionIcon variant="subtle" color="gray" size="lg" aria-label={t('shell.notifications')} onClick={() => navigate(`/guild/${currentGuildId}/plans`)}>
              <Bell size={20} />
            </ActionIcon>
          </Tooltip>
          <LanguageSelector />
          <Tooltip label={t('shell.account')}>
            <button type="button" className="bunny-topbar-avatar" onClick={() => setCommandOpen(true)} aria-label={t('shell.account')}>
              {userName.slice(0, 2).toUpperCase()}
            </button>
          </Tooltip>
        </div>
      </MantineAppShell.Header>

      <MantineAppShell.Main className="bunny-workspace">
        <main id="main" className="bunny-content">
          <Outlet context={{ me, guild, guilds: guilds.data, connection, capabilities: capabilityQuery.data } satisfies DashboardContext} />
        </main>
      </MantineAppShell.Main>

      <Drawer
        opened={navOpen}
        onClose={() => setNavOpen(false)}
        title={t('shell.navigation')}
        size="min(86vw, 320px)"
        padding={0}
        hiddenFrom="md"
        classNames={{ content: 'bunny-mobile-drawer', header: 'bunny-mobile-drawer-header', body: 'bunny-mobile-drawer-body' }}
        closeButtonProps={{ 'aria-label': t('shell.closeNavigation') }}
      >
        {navigation(true)}
      </Drawer>

      <nav className="bunny-bottom-nav" aria-label={t('shell.navigation')}>
        {primaryNavigation.map((item) => {
          const Icon = item.icon
          const active = item.sections.includes(activeSection)
          return (
            <NavLink key={item.section} to={`/guild/${currentGuildId}/${item.section}`} className={active ? 'active' : ''}>
              <Icon size={21} strokeWidth={active ? 2.5 : 2} />
              <span>{t(item.labelKey)}</span>
            </NavLink>
          )
        })}
      </nav>

      <CommandPalette guild={guild} capabilities={capabilityQuery.data} />
    </MantineAppShell>
  )
}
