import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { MessageKey } from '../../localization/catalog'
import type { DashboardContext } from '../../app/AppShell'
import { Badge } from '../../shared/components/ui'
import { wizardCatalog } from './catalog'

/**
 * Catalog screen (REQ-WIZ-002): entry point for every guided assistant, distinct from Policies,
 * Plans and Templates. Only "access-space" launches today; other entries are shown but disabled
 * with an explicit reason rather than hidden or faked as usable.
 */
export function AssistantsScreen() {
  const { t } = useTranslation()
  const { guild } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()

  return (
    <section className="access-page wizards-catalog">
      <header className="access-hero">
        <div>
          <p className="access-eyebrow">{t('access.eyebrow')}</p>
          <h1>{t('wizards.title')}</h1>
          <p>{t('wizards.subtitle')}</p>
        </div>
      </header>

      <div className="wizards-catalog-grid">
        {wizardCatalog.map((entry) => (
          <article key={entry.id} className="access-panel wizard-catalog-card">
            <div className="access-panel-heading">
              <div><strong>{t(entry.titleKey as MessageKey)}</strong></div>
              <Badge tone={entry.availability === 'available' ? 'ok' : 'neutral'}>
                {t(entry.availability === 'available' ? 'wizards.catalog.available' : 'wizards.catalog.unavailable')}
              </Badge>
            </div>
            <p>{t(entry.goalKey as MessageKey)}</p>
            <dl>
              <div><dt>{t('wizards.catalog.scope')}</dt><dd>{t(entry.scopeKey as MessageKey)}</dd></div>
              <div><dt>{t('wizards.catalog.produces')}</dt><dd>{t(entry.producesKey as MessageKey)}</dd></div>
              <div><dt>{t('wizards.catalog.prerequisites')}</dt><dd>{t(entry.prerequisitesKey as MessageKey)}</dd></div>
              <div><dt>{t('wizards.catalog.complexity')}</dt><dd>{t(entry.complexityKey as MessageKey)}</dd></div>
            </dl>
            {entry.availability === 'available'
              ? <button type="button" className="button primary" onClick={() => navigate(`/guild/${guild.guild_id}/wizards/${entry.route}`)}>{t('wizards.catalog.start')}</button>
              : <p className="access-callout warning">{t(entry.unavailableReasonKey as MessageKey)}</p>}
          </article>
        ))}
      </div>
    </section>
  )
}
