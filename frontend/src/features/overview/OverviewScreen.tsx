import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useRoles, useStructure } from '../../api/queries'
import type { DashboardContext } from '../../app/AppShell'
import { Badge } from '../../shared/components/ui'

export function OverviewScreen() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { me, guild, connection, capabilities } = useOutletContext<DashboardContext>()
  const structure = useStructure(me.user.discord_user_id, guild.guild_id)
  const roles = useRoles(me.user.discord_user_id, guild.guild_id)

  const channelCount = structure.data
    ? structure.data.root_channels.length + structure.data.categories.reduce((count, category) => count + category.channels.length + 1, 0)
    : null
  const roleCount = roles.data?.roles.length ?? null
  const coverage = capabilities?.coverage ?? 'UNKNOWN'
  const freshness = capabilities?.freshness ?? 'UNKNOWN'

  const connectionLabel = connection === 'live'
    ? t('connection.live')
    : connection === 'offline'
      ? t('errors.network.offline')
      : connection === 'unauthorized'
        ? t('errors.authorization.denied')
        : t('connection.reconnecting')

  return (
    <section className="overview-page">
      <header className="overview-hero">
        <div>
          <p className="eyebrow">{guild.name}</p>
          <h1>{t('overview.title')}</h1>
          <p>{t('overview.subtitle')}</p>
        </div>
        <div className="overview-hero-actions">
          <button type="button" className="button quiet" onClick={() => navigate(`/guild/${guild.guild_id}/diagnostics`)}>{t('overview.openDiagnostics')}</button>
          <button type="button" className="button primary" onClick={() => navigate(`/guild/${guild.guild_id}/structure`)}>{t('overview.openStructure')}</button>
        </div>
      </header>

      <div className="overview-grid">
        <article className="overview-card accent-card">
          <span className="overview-card-icon">⌘</span>
          <div><small>{t('overview.structure')}</small><strong>{channelCount ?? '—'}</strong><span>{structure.isError ? t('errors.network.offline') : t('structure.title')}</span></div>
        </article>
        <article className="overview-card">
          <span className="overview-card-icon">◇</span>
          <div><small>{t('overview.roles')}</small><strong>{roleCount ?? '—'}</strong><span>{roles.isError ? t('errors.network.offline') : t('roles.title')}</span></div>
        </article>
        <article className="overview-card">
          <span className="overview-card-icon">◌</span>
          <div><small>{t('overview.coverage')}</small><strong>{coverage}</strong><span>{freshness}</span></div>
        </article>
        <article className="overview-card">
          <span className={`overview-card-icon connection-dot ${connection}`}>●</span>
          <div><small>{t('overview.connection')}</small><strong>{connection === 'live' ? 'LIVE' : connection.toUpperCase()}</strong><span>{connectionLabel}</span></div>
        </article>
      </div>

      <div className="overview-lower-grid">
        <article className="overview-panel">
          <div className="panel-heading"><div><p className="eyebrow">Discord</p><h2>{t('diagnostics.capabilities')}</h2></div><Badge tone={coverage === 'FULL' ? 'ok' : 'warning'}>{coverage}</Badge></div>
          <div className="capability-summary">
            {Object.entries(capabilities?.bot_operations ?? {}).slice(0, 8).map(([name, decision]) => (
              <div className="capability-row" key={name}>
                <span>{name.replaceAll('_', ' ')}</span>
                <Badge tone={decision.outcome === 'CAN' ? 'ok' : decision.outcome === 'CANNOT' ? 'danger' : 'warning'}>{decision.outcome}</Badge>
              </div>
            ))}
            {!capabilities && <p className="muted-copy">{t('common.loading')}</p>}
          </div>
        </article>

        <article className="overview-panel server-summary-panel">
          <div className="server-summary-emblem">{guild.name.slice(0, 2).toUpperCase()}</div>
          <div><p className="eyebrow">{t('resource.guild')}</p><h2>{guild.name}</h2><p className="muted-copy">ID {guild.guild_id}</p></div>
          <Badge tone={guild.installation_status === 'ACTIVE' ? 'ok' : 'warning'}>{guild.installation_status ?? t('common.unknown')}</Badge>
        </article>
      </div>
    </section>
  )
}
